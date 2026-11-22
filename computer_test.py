import time
import pyautogui

# SAFETY: slam mouse into a corner to abort if something goes wrong
pyautogui.FAILSAFE = True   # default, but be explicit

print("JARVIS Computer Control Test")
print("Click into a text editor NOW. Starting in 5 seconds...")

# Give yourself a visible countdown
for i in range(5, 0, -1):
    print(f"{i}...")
    time.sleep(1)

width, height = pyautogui.size()
print(f"Screen size: {width}x{height}")

# Optional: focus the target window by title instead of relying on focus
# import pygetwindow as gw
# try:
#     gw.getWindowsWithTitle("Notepad")[0].activate()
#     time.sleep(0.3)
# except IndexError:
#     print("No Notepad window found — open Notepad first.")

pyautogui.moveTo(width // 2, height // 2, duration=1)
pyautogui.moveRel(100, 0, duration=1)

# Type something harmless first so you can confirm the target
pyautogui.write("JARVIS test: ", interval=0.04)
pyautogui.write("Hello! JARVIS computer control is working.", interval=0.04)

print("Computer control test completed.")
