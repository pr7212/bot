"""
Local vision-based screen analysis for JARVIS (replacement for tools/screen.py).

Main fixes compared with the original:

  1. COORDINATES. Qwen3-VL reports positions on a relative 0-1000 grid, not in
     screen pixels. The original asked for pixels, so clicks would land in the
     wrong place (x=500 on a 1920-wide screen is really pixel 960). This file
     states the scale explicitly in the prompt and converts every coordinate to
     real screen pixels before returning it.
  2. TOLERANT PARSING. One slightly bad element (a float, a value just out of
     range, 21 elements) used to throw away the whole analysis. Bad elements
     are now dropped or clamped, and the rest are kept. One retry on bad JSON.
  3. IMAGE SIZE. The screenshot is downscaled before it is sent, which makes
     the 4B model faster and gives a known image size for conversion.
  4. CALIBRATION. `python -m tools.screen calibrate` measures which coordinate
     convention your installed model really follows, using a test image with
     known positions.
  5. OVERLAY. `python -m tools.screen overlay` saves a screenshot with numbered
     markers where JARVIS would click, so you can SEE whether it is right.

Requires: pillow (pip install pillow)
"""

import io
import json
import re
import sys

from datetime import datetime
from pathlib import Path

import ollama
from PIL import Image, ImageDraw

from tools import computer


# ==========================================
# SETTINGS
# ==========================================

VISION_MODEL = "qwen3-vl:4b"
KEEP_ALIVE = "10m"

MAX_ELEMENTS = 20
MAX_IMAGE_WIDTH = 1280     # screenshots wider than this are downscaled
ATTEMPTS = 2               # tries when the model returns unusable output

# How the model reports positions:
#   "relative_1000" -> 0-1000 grid over the whole image (Qwen3-VL default)
#   "image_pixels"  -> pixels of the image that was sent
# Run `python -m tools.screen calibrate` to see which one your model follows.
COORD_MODE = "relative_1000"

# Keep clicks away from the extreme edge (corners trigger PyAutoGUI's FAILSAFE).
EDGE_MARGIN = 1

SCREENSHOT_DIR = Path(__file__).resolve().parent.parent / "screenshots"


# ==========================================
# SCREEN AND IMAGE HELPERS
# ==========================================

def _screen_size():
    """Return (width, height) of the click coordinate space."""
    size = computer.get_screen_size()

    if isinstance(size, dict):
        return int(size["width"]), int(size["height"])

    if isinstance(size, (list, tuple)) and len(size) >= 2:
        return int(size[0]), int(size[1])

    return int(size.width), int(size.height)


def _load_screenshot():
    """Take a screenshot and return it as a PIL image, whatever
    computer.take_screenshot() happens to return (path, bytes or image)."""
    shot = computer.take_screenshot()

    if isinstance(shot, Image.Image):
        return shot.convert("RGB")

    if isinstance(shot, (bytes, bytearray)):
        return Image.open(io.BytesIO(shot)).convert("RGB")

    return Image.open(str(shot)).convert("RGB")


def _prepare_image(image):
    """Downscale if needed. Returns (png_bytes, (width, height) sent)."""
    if image.width > MAX_IMAGE_WIDTH:
        ratio = MAX_IMAGE_WIDTH / image.width
        image = image.resize(
            (MAX_IMAGE_WIDTH, max(1, round(image.height * ratio))),
            Image.LANCZOS,
        )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    return buffer.getvalue(), image.size


# ==========================================
# COORDINATE CONVERSION
# ==========================================

def _convert(x, y, mode, image_size, screen_size):
    """Model coordinates -> screen pixels (floats, not yet clamped)."""
    image_w, image_h = image_size
    screen_w, screen_h = screen_size

    if mode == "relative_1000":
        return x / 1000 * screen_w, y / 1000 * screen_h

    if mode == "image_pixels":
        return x / image_w * screen_w, y / image_h * screen_h

    raise ValueError(f"Unknown COORD_MODE: {mode}")


def _in_range(x, y, mode, image_size):
    """Reject values that are clearly in the wrong coordinate system.
    A little overshoot is tolerated and clamped later."""
    if mode == "relative_1000":
        limit_x = limit_y = 1000
    else:
        limit_x, limit_y = image_size

    return (
        -0.02 * limit_x <= x <= 1.02 * limit_x
        and -0.02 * limit_y <= y <= 1.02 * limit_y
    )


def _clamp(value, size):
    return max(EDGE_MARGIN, min(int(round(value)), size - 1 - EDGE_MARGIN))


def _number(value):
    """Accept 12, 12.0 and '12'; reject everything else."""
    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None

    return None


def _element_point(element):
    """Find the element's centre in whichever form the model used."""
    x = _number(element.get("x"))
    y = _number(element.get("y"))

    if x is not None and y is not None:
        return x, y

    point = element.get("point_2d") or element.get("point")

    if isinstance(point, (list, tuple)) and len(point) >= 2:
        px, py = _number(point[0]), _number(point[1])

        if px is not None and py is not None:
            return px, py

    box = element.get("bbox_2d") or element.get("bbox")

    if isinstance(box, (list, tuple)) and len(box) >= 4:
        values = [_number(v) for v in box[:4]]

        if None not in values:
            return (values[0] + values[2]) / 2, (values[1] + values[3]) / 2

    return None


# ==========================================
# PARSING AND CLEANING
# ==========================================

def _parse_json(content):
    if not isinstance(content, str) or not content.strip():
        raise ValueError(
            "Vision model returned an empty response "
            "(is the model pulled and does it fit in memory?)."
        )

    text = content.strip()

    # Strip markdown fences if the model added them.
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)

        if not match:
            raise ValueError("Vision model did not return JSON.")

        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as error:
            raise ValueError(f"Vision model returned invalid JSON: {error}")

    if not isinstance(data, dict):
        raise ValueError("Vision model response must be a JSON object.")

    return data


def _clean(data, mode, image_size, screen_size):
    """Validate leniently: keep what is usable, drop the rest."""
    summary = data.get("screen_summary")
    elements = data.get("elements")

    if not isinstance(elements, list):
        raise ValueError("Vision model response must include an elements list.")

    if not isinstance(summary, str):
        summary = ""

    screen_w, screen_h = screen_size
    cleaned = []
    dropped = 0

    for element in elements:
        if len(cleaned) >= MAX_ELEMENTS:
            dropped += 1
            continue

        if not isinstance(element, dict):
            dropped += 1
            continue

        label = element.get("label")

        if not isinstance(label, str) or not label.strip():
            dropped += 1
            continue

        point = _element_point(element)

        if point is None or not _in_range(point[0], point[1], mode, image_size):
            dropped += 1
            continue

        sx, sy = _convert(point[0], point[1], mode, image_size, screen_size)

        role = element.get("role")

        cleaned.append({
            "label": label.strip()[:80],
            "role": role.strip()[:30] if isinstance(role, str) else "other",
            "x": _clamp(sx, screen_w),
            "y": _clamp(sy, screen_h),
        })

    return {
        "screen_summary": summary.strip()[:300],
        "screen_size": {"width": screen_w, "height": screen_h},
        "coordinate_space": "screen_pixels",
        "elements": cleaned,
        "dropped_elements": dropped,
    }


# ==========================================
# MODEL CALL
# ==========================================

_JSON_SHAPE = (
    '{"screen_summary":"brief description","elements":'
    '[{"label":"visible label","role":"button, window, menu, '
    'text field, text, or other","x":123,"y":456}]}'
)


def _build_prompt(mode, image_size):
    if mode == "relative_1000":
        scale = (
            "x and y use a relative 0-1000 grid over the whole image: "
            "(0, 0) is the top-left corner and (1000, 1000) is the "
            "bottom-right corner."
        )
    else:
        scale = (
            f"x and y are pixel positions in this image, which is "
            f"{image_size[0]} pixels wide and {image_size[1]} pixels high; "
            "(0, 0) is the top-left corner."
        )

    return (
        f"Describe the visible screen and identify up to {MAX_ELEMENTS} "
        "useful visible interface elements. Return only JSON with this "
        f"shape: {_JSON_SHAPE}. x and y are integers giving the center of "
        f"each element. {scale} Include only clearly visible elements; do "
        "not guess missing labels or invent controls."
    )


def _chat(messages):
    kwargs = {
        "model": VISION_MODEL,
        "messages": messages,
        "format": "json",
        "keep_alive": KEEP_ALIVE,
        "options": {"temperature": 0, "num_predict": 1800},
    }

    # Thinking-capable vision builds can burn time reasoning; turn it off,
    # but fall back cleanly if this model does not accept the flag.
    try:
        return ollama.chat(think=False, **kwargs)
    except Exception as error:
        if "think" in str(error).lower():
            return ollama.chat(**kwargs)
        raise


def _ask_model(png_bytes, mode, image_size):
    messages = [{
        "role": "user",
        "content": _build_prompt(mode, image_size),
        "images": [png_bytes],
    }]

    response = _chat(messages)

    return _parse_json(response.message.content)


# ==========================================
# PUBLIC API
# ==========================================

def analyze_screen():
    """Capture the desktop and identify visible elements.

    Returns coordinates in REAL SCREEN PIXELS, ready for click_mouse.
    """
    screen_size = _screen_size()
    image = _load_screenshot()
    png_bytes, image_size = _prepare_image(image)

    last_error = None

    for _ in range(ATTEMPTS):
        try:
            data = _ask_model(png_bytes, COORD_MODE, image_size)
            return _clean(data, COORD_MODE, image_size, screen_size)
        except ValueError as error:
            last_error = error

    raise ValueError(
        f"Screen analysis failed after {ATTEMPTS} attempts: {last_error}"
    )


# ==========================================
# CALIBRATION AND OVERLAY (run from the command line)
# ==========================================

# (colour name, RGB, centre as a fraction of the image)
_CALIBRATION_SQUARES = [
    ("red",    (220, 30, 30),   (0.15, 0.20)),
    ("green",  (30, 170, 60),   (0.80, 0.25)),
    ("blue",   (40, 70, 220),   (0.50, 0.50)),
    ("yellow", (240, 210, 20),  (0.20, 0.80)),
    ("purple", (140, 50, 180),  (0.85, 0.85)),
]


def _calibration_image(width=1280, height=720, half=45):
    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)

    for _, color, (fx, fy) in _CALIBRATION_SQUARES:
        cx, cy = fx * width, fy * height
        draw.rectangle([cx - half, cy - half, cx + half, cy + half], fill=color)

    return image


def calibrate():
    """Ask the model to locate known squares under both conventions and
    report which one is accurate. Needs the vision model running."""
    image = _calibration_image()
    png_bytes, image_size = _prepare_image(image)
    screen_size = image_size   # compare in image space; only fractions matter

    prompt_tail = (
        "The image contains five solid colored squares on a white "
        "background: red, green, blue, yellow and purple. Locate the center "
        "of each square. Use label text like 'red square'."
    )

    results = {}

    for mode in ("relative_1000", "image_pixels"):
        messages = [{
            "role": "user",
            "content": _build_prompt(mode, image_size) + " " + prompt_tail,
            "images": [png_bytes],
        }]

        try:
            data = _parse_json(_chat(messages).message.content)
        except Exception as error:
            results[mode] = {"error": str(error)}
            continue

        errors = []
        found = 0

        for name, _, (fx, fy) in _CALIBRATION_SQUARES:
            for element in data.get("elements", []):
                label = str(element.get("label", "")).lower()
                point = _element_point(element) if isinstance(element, dict) else None

                if name in label and point is not None:
                    sx, sy = _convert(point[0], point[1], mode, image_size, screen_size)
                    ex = abs(sx / screen_size[0] - fx)
                    ey = abs(sy / screen_size[1] - fy)
                    errors.append(max(ex, ey))
                    found += 1
                    break

        results[mode] = {
            "found": found,
            "mean_error": (sum(errors) / len(errors)) if errors else None,
        }

    print("\nCalibration results (error is a fraction of screen width/height):")

    best_mode, best_error = None, None

    for mode, info in results.items():
        if "error" in info:
            print(f"  {mode:14s}  FAILED: {info['error']}")
            continue

        if info["mean_error"] is None:
            print(f"  {mode:14s}  located 0 of 5 squares")
            continue

        print(
            f"  {mode:14s}  located {info['found']} of 5, "
            f"mean error {info['mean_error'] * 100:.1f}%"
        )

        if best_error is None or info["mean_error"] < best_error:
            best_mode, best_error = mode, info["mean_error"]

    if best_mode is None:
        print("\nCould not calibrate. Is the model installed and running?")
        return None

    print(f'\nRecommended setting: COORD_MODE = "{best_mode}"')

    if best_error > 0.05:
        print(
            "WARNING: even the best mode is off by more than 5% of the "
            "screen. Clicks based on this model's coordinates will be "
            "unreliable; verify with the overlay command and prefer "
            "keyboard shortcuts where possible."
        )

    return best_mode


def save_overlay():
    """Save a screenshot with numbered markers at the coordinates JARVIS
    would click, so the accuracy can be checked by eye."""
    analysis = analyze_screen()
    image = _load_screenshot()
    draw = ImageDraw.Draw(image)

    screen_w, screen_h = _screen_size()
    scale_x = image.width / screen_w
    scale_y = image.height / screen_h

    for number, element in enumerate(analysis["elements"], start=1):
        cx = element["x"] * scale_x
        cy = element["y"] * scale_y
        r = max(8, image.width // 160)

        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 0, 0), width=3)
        draw.text((cx + r + 3, cy - r), f"{number}: {element['label']}", fill=(255, 0, 0))

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOT_DIR / datetime.now().strftime("overlay_%Y%m%d_%H%M%S.png")
    image.save(path)

    print(f"Saved overlay: {path}")
    print(f"Summary: {analysis['screen_summary']}")

    for number, element in enumerate(analysis["elements"], start=1):
        print(f"  {number}. {element['label']} ({element['role']}) "
              f"at ({element['x']}, {element['y']})")

    return str(path)


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""

    if command == "calibrate":
        calibrate()
    elif command == "overlay":
        save_overlay()
    else:
        print("Usage:")
        print("  python -m tools.screen calibrate   # which coordinate system does the model use?")
        print("  python -m tools.screen overlay     # screenshot with markers where JARVIS would click")
