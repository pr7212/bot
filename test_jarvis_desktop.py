import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import jarvis


class JarvisDesktopActionTests(unittest.TestCase):
    @staticmethod
    def tool_call(name, arguments):
        return SimpleNamespace(
            function=SimpleNamespace(name=name, arguments=arguments)
        )

    def test_desktop_actions_require_approval_and_return_observation(self):
        observation = {
            "screen_summary": "An application window.",
            "elements": [],
        }
        click = Mock(return_value="Clicked at (50, 60).")

        with (
            patch("builtins.input", return_value="y"),
            patch.dict(jarvis.AVAILABLE_FUNCTIONS, {"click_mouse": click}),
            patch("jarvis.screen.analyze_screen", return_value=observation) as analyze,
        ):
            result = jarvis.execute_tool(
                self.tool_call("click_mouse", {"x": 50, "y": 60})
            )

        click.assert_called_once_with(x=50, y=60)
        analyze.assert_called_once_with()
        self.assertIn('"screen_summary": "An application window."', result)

    def test_denied_action_does_not_run_or_observe(self):
        click = Mock()
        with (
            patch("builtins.input", return_value="n"),
            patch.dict(jarvis.AVAILABLE_FUNCTIONS, {"click_mouse": click}),
            patch("jarvis.screen.analyze_screen") as analyze,
        ):
            result = jarvis.execute_tool(
                self.tool_call("click_mouse", {"x": 50, "y": 60})
            )

        self.assertEqual(result, "Action denied by user.")
        click.assert_not_called()
        analyze.assert_not_called()

    def test_second_desktop_action_waits_for_screen_feedback(self):
        click = Mock(return_value="Clicked.")
        type_text = Mock(return_value="Typed.")
        first_response = SimpleNamespace(
            message=SimpleNamespace(
                tool_calls=[
                    self.tool_call("click_mouse", {"x": 50, "y": 60}),
                    self.tool_call("type_text", {"text": "next"}),
                ],
                content=None,
            )
        )
        final_response = SimpleNamespace(
            message=SimpleNamespace(tool_calls=None, content="Finished.")
        )

        with (
            patch("builtins.input", return_value="y"),
            patch.dict(
                jarvis.AVAILABLE_FUNCTIONS,
                {"click_mouse": click, "type_text": type_text},
            ),
            patch("jarvis.screen.analyze_screen", return_value={"elements": []}),
            patch(
                "jarvis.ollama.chat",
                side_effect=[first_response, final_response],
            ) as chat,
        ):
            result = jarvis.ask_jarvis("Click, then type.", max_steps=2)

        self.assertEqual(result, "Finished.")
        self.assertEqual(chat.call_count, 2)
        click.assert_called_once_with(x=50, y=60)
        type_text.assert_not_called()


if __name__ == "__main__":
    unittest.main()
