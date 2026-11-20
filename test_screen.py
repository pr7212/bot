import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tools import screen


class ScreenAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.analysis = {
            "screen_summary": "A window with a Save button.",
            "elements": [
                {"label": "Save", "role": "button", "x": 80, "y": 40}
            ],
        }

    @patch("tools.screen.computer.get_screen_size", return_value={"width": 800, "height": 600})
    @patch("tools.screen.ollama.chat")
    @patch("tools.screen.computer.take_screenshot", return_value="screen.png")
    def test_analyze_screen_sends_local_image_and_validates_result(
        self, take_screenshot, chat, get_screen_size
    ):
        chat.return_value = SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(self.analysis))
        )

        result = screen.analyze_screen()

        self.assertEqual(result, self.analysis)
        self.assertEqual(chat.call_args.kwargs["model"], "qwen3-vl:4b")
        self.assertEqual(
            chat.call_args.kwargs["messages"][0]["images"], ["screen.png"]
        )
        take_screenshot.assert_called_once_with()
        get_screen_size.assert_called_once_with()

    @patch("tools.screen.computer.get_screen_size", return_value={"width": 800, "height": 600})
    @patch("tools.screen.ollama.chat")
    @patch("tools.screen.computer.take_screenshot", return_value="screen.png")
    def test_invalid_coordinates_are_rejected(
        self, take_screenshot, chat, get_screen_size
    ):
        invalid = {
            "screen_summary": "A window.",
            "elements": [
                {"label": "Save", "role": "button", "x": 800, "y": 40}
            ],
        }
        chat.return_value = SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(invalid))
        )

        with self.assertRaisesRegex(ValueError, "invalid x coordinate"):
            screen.analyze_screen()

    @patch("tools.screen.computer.get_screen_size", return_value={"width": 800, "height": 600})
    @patch("tools.screen.ollama.chat")
    @patch("tools.screen.computer.take_screenshot", return_value="screen.png")
    def test_malformed_model_response_is_reported(
        self, take_screenshot, chat, get_screen_size
    ):
        chat.return_value = SimpleNamespace(
            message=SimpleNamespace(content="not JSON")
        )

        with self.assertRaisesRegex(ValueError, "invalid JSON"):
            screen.analyze_screen()


if __name__ == "__main__":
    unittest.main()
