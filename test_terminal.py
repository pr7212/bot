import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import terminal


class TerminalCommandTests(unittest.TestCase):
    @patch("tools.terminal.shutil.which", return_value="C:\\Tools\\node.exe")
    @patch("tools.terminal.subprocess.run")
    def test_command_runs_without_shell_and_returns_bounded_results(
        self, run, which
    ):
        run.return_value = subprocess.CompletedProcess(
            args=["C:\\Tools\\node.exe", "app.js"],
            returncode=0,
            stdout="ok",
            stderr="",
        )

        result = terminal.run_command("node", ["app.js"], timeout=12)

        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["stdout"], "ok")
        self.assertEqual(result["cwd"], ".")
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertEqual(run.call_args.kwargs["timeout"], 12)

    def test_allowlist_arguments_and_working_directory_are_validated(self):
        with self.assertRaises(ValueError):
            terminal.run_command("powershell", ["-Command", "Write-Host unsafe"])
        with self.assertRaises(ValueError):
            terminal.run_command("node", "app.js")
        with self.assertRaises(ValueError):
            terminal.run_command("node", ["app.js"], cwd="..")
        with self.assertRaises(ValueError):
            terminal.run_command("node", ["app.js"], timeout=301)

    @patch("tools.terminal.os.name", "nt")
    @patch("tools.terminal.shutil.which")
    @patch("tools.terminal.subprocess.run")
    def test_npm_batch_launcher_is_replaced_with_native_node_cli(
        self, run, which
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            node_dir = Path(temp_dir)
            npm_wrapper = node_dir / "npm.cmd"
            npm_wrapper.touch()
            npm_cli = node_dir / "node_modules" / "npm" / "bin" / "npm-cli.js"
            npm_cli.parent.mkdir(parents=True)
            npm_cli.touch()
            node_executable = node_dir / "node.exe"
            node_executable.touch()
            which.side_effect = [str(npm_wrapper), str(node_executable)]
            run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )

            terminal.run_command("npm", ["test"])

            self.assertEqual(
                run.call_args.args[0],
                [str(node_executable), str(npm_cli), "test"],
            )
            self.assertFalse(run.call_args.kwargs["shell"])

    @patch("tools.terminal.shutil.which", return_value="C:\\Tools\\node.exe")
    @patch("tools.terminal.subprocess.run")
    def test_output_is_truncated(self, run, which):
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="x" * (terminal.MAX_OUTPUT_SIZE + 1),
            stderr="",
        )

        result = terminal.run_command("node", ["app.js"])

        self.assertTrue(result["stdout"].endswith("[Output truncated]"))
        self.assertLessEqual(len(result["stdout"]), terminal.MAX_OUTPUT_SIZE + 20)


if __name__ == "__main__":
    unittest.main()
