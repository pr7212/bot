import unittest
from unittest.mock import patch

from tools import computer


class ComputerControlTests(unittest.TestCase):
    @patch("tools.computer.pyautogui.size", return_value=(800, 600))
    @patch("tools.computer.pyautogui.rightClick")
    def test_right_click_checks_screen_coordinates(self, right_click, screen_size):
        result = computer.right_click_mouse(100, 200)

        self.assertEqual(result, "Right-clicked at (100, 200).")
        right_click.assert_called_once_with(100, 200)
        with self.assertRaises(ValueError):
            computer.right_click_mouse(800, 200)

    @patch("tools.computer.pyautogui.scroll")
    @patch("tools.computer.pyautogui.size", return_value=(800, 600))
    def test_scroll_direction_and_limits(self, screen_size, scroll):
        computer.scroll_mouse(-4, 100, 200)

        scroll.assert_called_once_with(-4, x=100, y=200)
        with self.assertRaises(ValueError):
            computer.scroll_mouse(51)
        with self.assertRaises(ValueError):
            computer.scroll_mouse(2, x=10)

    @patch("tools.computer.pyautogui.size", return_value=(800, 600))
    @patch("tools.computer.pyautogui.dragTo")
    @patch("tools.computer.pyautogui.moveTo")
    def test_drag_validates_both_endpoints(self, move_to, drag_to, screen_size):
        result = computer.drag_mouse(10, 20, 300, 400, duration=1)

        self.assertEqual(result, "Dragged from (10, 20) to (300, 400).")
        move_to.assert_called_once_with(10, 20)
        drag_to.assert_called_once_with(
            300, 400, duration=1, button="left"
        )
        with self.assertRaises(ValueError):
            computer.drag_mouse(10, 20, -1, 400)
        with self.assertRaises(ValueError):
            computer.drag_mouse(10, 20, 300, 400, duration=31)

    @patch("tools.computer.pyautogui.hotkey")
    def test_hotkey_and_select_replace(self, hotkey):
        with patch("tools.computer.pyautogui.write") as write:
            self.assertEqual(computer.press_hotkey(["CTRL", "s"]), "Pressed ctrl+s.")
            computer.select_all_and_replace_text("replacement")

        hotkey.assert_any_call("ctrl", "s")
        hotkey.assert_any_call("ctrl", "a")
        write.assert_called_once_with("replacement", interval=0.02)
        with self.assertRaises(ValueError):
            computer.press_hotkey(["not-a-real-key", "ctrl"])


if __name__ == "__main__":
    unittest.main()
