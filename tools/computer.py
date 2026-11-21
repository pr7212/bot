
import math
import subprocess
import time
from pathlib import Path

import pyautogui


# ==========================================
# CONFIGURATION
# ==========================================

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.3

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCREENSHOT_DIR = PROJECT_ROOT / "screenshots"

SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

MAX_TEXT_LENGTH = 10_000
MAX_SCROLL_CLICKS = 50
MAX_MOVEMENT_DURATION = 30
MAX_TYPING_INTERVAL = 1


# ==========================================
# VALIDATION
# ==========================================

def validate_coordinates(x: int, y: int) -> None:
    """Ensure coordinates are valid and inside the screen."""

    if (
        not isinstance(x, int)
        or isinstance(x, bool)
        or not isinstance(y, int)
        or isinstance(y, bool)
    ):
        raise TypeError("Coordinates must be integers.")

    width, height = pyautogui.size()

    if not (0 <= x < width and 0 <= y < height):
        raise ValueError(
            f"Coordinates must be within "
            f"x: 0-{width - 1}, y: 0-{height - 1}."
        )


def validate_duration(
    duration: float,
    maximum: float = MAX_MOVEMENT_DURATION
) -> None:
    """Validate a duration value."""

    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or duration < 0
        or duration > maximum
    ):
        raise ValueError(
            f"Duration must be between 0 and {maximum} seconds."
        )


def validate_text(text: str) -> None:
    """Validate text before typing."""

    if not isinstance(text, str):
        raise TypeError("Text must be a string.")

    if len(text) > MAX_TEXT_LENGTH:
        raise ValueError(
            f"Text exceeds the {MAX_TEXT_LENGTH}-character limit."
        )


def validate_key(key: str) -> str:
    """Validate and normalize a keyboard key."""

    if not isinstance(key, str):
        raise TypeError("Key must be a string.")

    key = key.lower()

    if key not in pyautogui.KEYBOARD_KEYS:
        raise ValueError(f"Unsupported keyboard key: {key}")

    return key


# ==========================================
# SCREEN INFORMATION
# ==========================================

def get_screen_size() -> dict:
    """Return screen dimensions."""

    width, height = pyautogui.size()

    return {
        "width": width,
        "height": height
    }


# ==========================================
# MOUSE CONTROL
# ==========================================

def move_mouse(
    x: int,
    y: int,
    duration: float = 0.3
) -> str:
    """Move the cursor to screen coordinates."""

    validate_coordinates(x, y)
    validate_duration(duration)

    pyautogui.moveTo(x, y, duration=duration)

    return f"Mouse moved to ({x}, {y})."


def click_mouse(x: int, y: int) -> str:
    """Move to coordinates and perform a left click."""

    validate_coordinates(x, y)

    pyautogui.click(x, y)

    return f"Clicked at ({x}, {y})."


def right_click_mouse(x: int, y: int) -> str:
    """Perform a right click."""

    validate_coordinates(x, y)

    pyautogui.rightClick(x, y)

    return f"Right-clicked at ({x}, {y})."


def double_click_mouse(x: int, y: int) -> str:
    """Perform a double click."""

    validate_coordinates(x, y)

    pyautogui.doubleClick(x, y)

    return f"Double-clicked at ({x}, {y})."


def scroll_mouse(
    clicks: int,
    x: int = None,
    y: int = None
) -> str:
    """Scroll vertically at an optional screen position."""

    if (
        not isinstance(clicks, int)
        or isinstance(clicks, bool)
        or clicks == 0
        or abs(clicks) > MAX_SCROLL_CLICKS
    ):
        raise ValueError(
            f"Scroll must be between "
            f"-{MAX_SCROLL_CLICKS} and {MAX_SCROLL_CLICKS}, excluding 0."
        )

    if (x is None) != (y is None):
        raise ValueError("Provide both x and y coordinates.")

    if x is not None:
        validate_coordinates(x, y)

    pyautogui.scroll(clicks, x=x, y=y)

    direction = "up" if clicks > 0 else "down"

    return f"Scrolled {direction} by {abs(clicks)} clicks."


def drag_mouse(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    duration: float = 0.5
) -> str:
    """Drag the left mouse button between two coordinates."""

    validate_coordinates(start_x, start_y)
    validate_coordinates(end_x, end_y)
    validate_duration(duration)

    pyautogui.moveTo(start_x, start_y)
    pyautogui.dragTo(
        end_x,
        end_y,
        duration=duration,
        button="left"
    )

    return (
        f"Dragged from ({start_x}, {start_y}) "
        f"to ({end_x}, {end_y})."
    )


# ==========================================
# KEYBOARD CONTROL
# ==========================================

def type_text(
    text: str,
    interval: float = 0.02
) -> str:
    """Type text into the currently focused application."""

    validate_text(text)
    validate_duration(interval, MAX_TYPING_INTERVAL)

    pyautogui.write(text, interval=interval)

    return "Text typed successfully."


def press_key(key: str) -> str:
    """Press a single keyboard key."""

    key = validate_key(key)

    pyautogui.press(key)

    return f"Pressed {key}."


def press_hotkey(keys: list) -> str:
    """Press a keyboard shortcut containing 2-4 keys."""

    if not isinstance(keys, list) or not 2 <= len(keys) <= 4:
        raise ValueError(
            "A shortcut must contain between 2 and 4 keys."
        )

    normalized_keys = [
        validate_key(key)
        for key in keys
    ]

    pyautogui.hotkey(*normalized_keys)

    return f"Pressed {'+'.join(normalized_keys)}."


def select_all_and_replace_text(text: str) -> str:
    """Replace text in the currently focused control."""

    validate_text(text)

    pyautogui.hotkey("ctrl", "a")
    pyautogui.write(text, interval=0.02)

    return "Selected content replaced."


# ==========================================
# SCREENSHOT CONTROL
# ==========================================

def take_screenshot() -> str:
    """Capture the screen and save it with a unique filename."""

    timestamp = time.time_ns()

    filename = f"jarvis_{timestamp}.png"
    filepath = SCREENSHOT_DIR / filename

    screenshot = pyautogui.screenshot()
    screenshot.save(filepath)

    return str(filepath)


# ==========================================
# APPLICATION CONTROL
# ==========================================

def open_notepad() -> str:
    """Launch Windows Notepad."""

    subprocess.Popen(
        ["notepad.exe"],
        shell=False
    )

    time.sleep(2)

    return "Notepad opened successfully."


# ==========================================
# TESTING
# ==========================================

if __name__ == "__main__":

    print("JARVIS COMPUTER CONTROL")
    print("=" * 30)

    print("Screen:", get_screen_size())

    print("Taking screenshot...")

    screenshot_path = take_screenshot()

    print("Screenshot saved:", screenshot_path)

    print("Computer control ready.")
