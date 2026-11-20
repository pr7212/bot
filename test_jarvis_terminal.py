import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import jarvis


class JarvisTerminalToolTests(unittest.TestCase):
    def test_terminal_command_requires_approval(self):
        with (
            patch("builtins.input", return_value="y"),
            patch.dict(
                jarvis.AVAILABLE_FUNCTIONS,
                {"run_command": lambda **kwargs: {"exit_code": 0}},
            ) as functions,
        ):
            result = jarvis.execute_tool(
                SimpleNamespace(
                    function=SimpleNamespace(
                        name="run_command",
                        arguments={
                            "command": "python",
                            "args": ["-m", "unittest"],
                        },
                    )
                )
            )

        self.assertEqual(result, '{"exit_code": 0}')

    def test_denied_terminal_command_is_not_run(self):
        command = Mock(return_value={"exit_code": 0})
        with (
            patch("builtins.input", return_value="n"),
            patch.dict(jarvis.AVAILABLE_FUNCTIONS, {"run_command": command}),
        ):
            result = jarvis.execute_tool(
                SimpleNamespace(
                    function=SimpleNamespace(
                        name="run_command",
                        arguments={"command": "npm", "args": ["install"]},
                    )
                )
            )

        self.assertEqual(result, "Action denied by user.")
        command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
