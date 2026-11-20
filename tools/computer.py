import math
import subprocess
import time
from pathlib import Path

import pyautogui

# Emergency stop: move the mouse to the top-left corner.
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.3

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCREENSHOT_DIR = PROJECT_ROOT / "screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


def get_screen_size():
    """Return screen dimensions."""
    width, height = pyautogui.size()
    return {
        "width": width,
        "height": height
    }


def validate_coordinates(x, y):
    """Ensure coordinates are inside the screen."""
    width, height = pyautogui.size()

    if (
        not isinstance(x, int)
        or isinstance(x, bool)
        or not isinstance(y, int)
        or isinstance(y, bool)
    ):
        raise TypeError("Coordinates must be integers.")

    if not (0 <= x < width and 0 <= y < height):
        raise ValueError(
            f"Coordinates must be within 0-{width - 1}, "
            f"0-{height - 1}."
        )


def validate_duration(duration, maximum=30):
    finite = False
    if isinstance(duration, (int, float)) and not isinstance(duration, bool):
        try:
            finite = math.isfinite(duration)
        except OverflowError:
            pass

    if (
        not finite
        or duration < 0
        or duration > maximum
    ):
        raise ValueError(
            f"Duration must be finite and between 0 and {maximum} seconds."
        )


def move_mouse(x: int, y: int, duration: float = 0.3):
    """Move the cursor to the given coordinates."""
    validate_coordinates(x, y)
    validate_duration(duration)

    pyautogui.moveTo(x, y, duration=duration)
    return f"Mouse moved to ({x}, {y})."


def click_mouse(x: int, y: int):
    """Move to coordinates and click."""
    move_mouse(x, y)
    pyautogui.click()
    return f"Clicked at ({x}, {y})."


def right_click_mouse(x: int, y: int):
    """Right-click at the given screen coordinates."""
    validate_coordinates(x, y)
    pyautogui.rightClick(x, y)
    return f"Right-clicked at ({x}, {y})."


def double_click_mouse(x: int, y: int):
    """Double-click at the given screen coordinates."""
    validate_coordinates(x, y)
    pyautogui.doubleClick(x, y)
    return f"Double-clicked at ({x}, {y})."


def scroll_mouse(clicks: int, x=None, y=None):
    """Scroll vertically; positive clicks scroll up and negative clicks down."""
    if (
        not isinstance(clicks, int)
        or isinstance(clicks, bool)
        or clicks == 0
        or abs(clicks) > 50
    ):
        raise ValueError("Scroll clicks must be an integer from -50 to 50, excluding 0.")
    if (x is None) != (y is None):
        raise ValueError("Provide both x and y to position the scroll.")
    if x is not None:
        validate_coordinates(x, y)

    pyautogui.scroll(clicks, x=x, y=y)
    direction = "up" if clicks > 0 else "down"
    return f"Scrolled {direction} by {abs(clicks)} clicks."


def drag_mouse(start_x: int, start_y: int, end_x: int, end_y: int, duration=0.5):
    """Drag the left mouse button between two screen coordinates."""
    validate_coordinates(start_x, start_y)
    validate_coordinates(end_x, end_y)
    validate_duration(duration)

    pyautogui.moveTo(start_x, start_y)
    pyautogui.dragTo(end_x, end_y, duration=duration, button="left")
    return f"Dragged from ({start_x}, {start_y}) to ({end_x}, {end_y})."


def type_text(text: str, interval: float = 0.02):
    """Type the given text."""
    if not isinstance(text, str):
        raise TypeError("Text must be a string.")
    validate_duration(interval, maximum=1)
    pyautogui.write(text, interval=interval)
    return "Text typed successfully."


def press_key(key: str):
    """Press a keyboard key."""
    if not isinstance(key, str):
        raise TypeError("Key must be a string.")

    key = key.lower()
    if key not in pyautogui.KEYBOARD_KEYS:
        raise ValueError(f"Unsupported keyboard key: {key}")
    pyautogui.press(key)
    return f"Pressed {key}."


def press_hotkey(keys):
    """Press a keyboard shortcut composed of two to four keys."""
    if not isinstance(keys, list) or not 2 <= len(keys) <= 4:
        raise ValueError("A shortcut must contain between 2 and 4 keys.")

    normalized_keys = []
    for key in keys:
        if not isinstance(key, str):
            raise TypeError("Shortcut keys must be strings.")
        key = key.lower()
        if key not in pyautogui.KEYBOARD_KEYS:
            raise ValueError(f"Unsupported keyboard key: {key}")
        normalized_keys.append(key)

    pyautogui.hotkey(*normalized_keys)
    return f"Pressed {'+'.join(normalized_keys)}."


def select_all_and_replace_text(text: str):
    """Select all text in the focused control and replace it."""
    if not isinstance(text, str):
        raise TypeError("Text must be a string.")

    pyautogui.hotkey("ctrl", "a")
    pyautogui.write(text, interval=0.02)
    return "Selected content replaced."


def take_screenshot():
    """Capture the screen and save it."""
    filename = f"jarvis_{int(time.time())}.png"
    filepath = SCREENSHOT_DIR / filename
    screenshot = pyautogui.screenshot()
    screenshot.save(filepath)
    return str(filepath)


def open_notepad():
    """Launch Windows Notepad."""
    subprocess.Popen(["notepad.exe"])
    time.sleep(2)
    return "Notepad opened successfully."


if __name__ == "__main__":
    print("JARVIS COMPUTER CONTROL")
    print("-----------------------")

    print("Screen:", get_screen_size())

    print(move_mouse(500, 400))

    print("Taking screenshot...")
    print(take_screenshot())

    print("Computer control ready.")