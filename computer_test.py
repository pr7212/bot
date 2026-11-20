
import time
import pyautogui

print("JARVIS Computer Control Test")
print("Starting in 5 seconds...")

time.sleep(5)

# Get screen dimensions
width, height = pyautogui.size()

print(f"Screen size: {width}x{height}")

# Move mouse to screen center
pyautogui.moveTo(
    width // 2,
    height // 2,
    duration=1
)

# Move mouse slightly
pyautogui.moveRel(
    100,
    0,
    duration=1
)

# Type a test message
pyautogui.write(
    "Hello! JARVIS computer control is working.",
    interval=0.04
)

print("Computer control test completed.")
