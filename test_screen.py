import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from tools import screen


class ScreenAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.screenshot = Path(self.temp_dir.name) / "screen.png"
        Image.new("RGB", (100, 80), "white").save(self.screenshot)

        self.size_patch = patch(
            "tools.screen.computer.get_screen_size",
            return_value={"width": 800, "height": 600},
        )
        self.chat_patch = patch("tools.screen.ollama.chat")
        self.shot_patch = patch(
            "tools.screen.computer.take_screenshot",
            return_value=str(self.screenshot),
        )
        self.get_screen_size = self.size_patch.start()
        self.chat = self.chat_patch.start()
        self.take_screenshot = self.shot_patch.start()

    def tearDown(self):
        self.shot_patch.stop()
        self.chat_patch.stop()
        self.size_patch.stop()
        self.temp_dir.cleanup()

    def test_analyze_screen_sends_local_image_and_converts_coordinates(self):
        analysis = {
            "screen_summary": "A window with a Save button.",
            "elements": [
                {"label": "Save", "role": "button", "x": 500, "y": 250}
            ],
        }
        self.chat.return_value = SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(analysis))
        )

        result = screen.analyze_screen()

        self.assertEqual(result["screen_summary"], "A window with a Save button.")
        self.assertEqual(result["elements"][0]["label"], "Save")
        # 0-1000 grid -> real screen pixels (500/1000*800, 250/1000*600).
        self.assertEqual(result["elements"][0]["x"], 400)
        self.assertEqual(result["elements"][0]["y"], 150)
        self.assertEqual(result["coordinate_space"], "screen_pixels")
        self.assertEqual(self.chat.call_args.kwargs["model"], "qwen3-vl:4b")
        image = self.chat.call_args.kwargs["messages"][0]["images"][0]
        self.assertTrue(image.startswith(b"\x89PNG"))
        self.take_screenshot.assert_called_once_with()
        self.get_screen_size.assert_called_once_with()

    def test_invalid_coordinates_are_dropped(self):
        invalid = {
            "screen_summary": "A window.",
            "elements": [
                {"label": "Save", "role": "button", "x": 5000, "y": 40}
            ],
        }
        self.chat.return_value = SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(invalid))
        )

        result = screen.analyze_screen()

        self.assertEqual(result["elements"], [])
        self.assertEqual(result["dropped_elements"], 1)

    def test_malformed_model_response_is_reported(self):
        self.chat.return_value = SimpleNamespace(
            message=SimpleNamespace(content="not JSON")
        )

        with self.assertRaisesRegex(ValueError, "did not return JSON"):
            screen.analyze_screen()


if __name__ == "__main__":
    unittest.main()
