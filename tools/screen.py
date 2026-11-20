"""Local vision-based screen analysis for JARVIS."""

import json

import ollama

from tools import computer

VISION_MODEL = "qwen3-vl:4b"
MAX_ELEMENTS = 20


def _validate_analysis(content, screen_size):
    try:
        analysis = json.loads(content)
    except (json.JSONDecodeError, TypeError) as error:
        raise ValueError(f"Vision model returned invalid JSON: {error}") from error

    if not isinstance(analysis, dict):
        raise ValueError("Vision model response must be a JSON object.")

    summary = analysis.get("screen_summary")
    elements = analysis.get("elements")
    if not isinstance(summary, str) or not isinstance(elements, list):
        raise ValueError(
            "Vision model response must include screen_summary and elements."
        )
    if len(elements) > MAX_ELEMENTS:
        raise ValueError(f"Vision model returned more than {MAX_ELEMENTS} elements.")

    width = screen_size["width"]
    height = screen_size["height"]
    for index, element in enumerate(elements):
        if not isinstance(element, dict):
            raise ValueError(f"Element {index} must be a JSON object.")
        if not isinstance(element.get("label"), str) or not isinstance(
            element.get("role"), str
        ):
            raise ValueError(f"Element {index} must include label and role text.")
        for coordinate, upper_bound in (("x", width), ("y", height)):
            value = element.get(coordinate)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 0 <= value < upper_bound
            ):
                raise ValueError(
                    f"Element {index} has an invalid {coordinate} coordinate."
                )
    return analysis


def analyze_screen():
    """Capture the desktop and identify visible interface elements locally."""
    screenshot_path = computer.take_screenshot()
    response = ollama.chat(
        model=VISION_MODEL,
        messages=[
            {
                "role": "user",
                "content": (
                    "Describe the visible screen and identify up to 20 useful "
                    "visible interface elements. Return only JSON with this shape: "
                    '{"screen_summary":"brief description","elements":'
                    '[{"label":"visible label","role":"button, window, menu, '
                    'text field, text, or other","x":123,"y":456}]}. '
                    "Coordinates must be integer screen pixels at the center of "
                    "each element. Include only clearly visible elements; do not "
                    "guess missing labels or invent controls."
                ),
                "images": [screenshot_path],
            }
        ],
        format="json",
        options={"temperature": 0},
    )
    return _validate_analysis(
        response.message.content,
        computer.get_screen_size(),
    )
