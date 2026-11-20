"""Approval-gated developer command execution without a shell."""

import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

from tools.workspace import WORKSPACE

ALLOWED_COMMANDS = frozenset({"python", "node", "npm", "npx", "git", "php"})
IGNORED_CWD_PARTS = frozenset(
    {".git", ".venv", "venv", "__pycache__", "node_modules", ".jarvis_backups"}
)
MAX_ARGUMENTS = 64
MAX_ARGUMENT_LENGTH = 4096
MAX_TIMEOUT_SECONDS = 300
MAX_OUTPUT_SIZE = 12_000


def _resolve_working_directory(cwd):
    if not isinstance(cwd, str) or not cwd.strip():
        raise ValueError("cwd must be a relative directory inside the workspace.")

    requested = Path(cwd)
    if requested.is_absolute():
        raise ValueError("Absolute working directories are not allowed.")

    workspace_root = WORKSPACE.resolve()
    target = (workspace_root / requested).resolve()
    try:
        relative = target.relative_to(workspace_root)
    except ValueError as error:
        raise ValueError("Working directory must stay inside the workspace.") from error

    if any(part.casefold() in IGNORED_CWD_PARTS for part in relative.parts):
        raise ValueError("This working directory is restricted.")
    if not target.is_dir():
        raise NotADirectoryError(f"Working directory not found: {cwd}")

    return target, str(relative) if relative.parts else "."


def _resolve_executable(command):
    if command == "python":
        return [sys.executable]

    executable = shutil.which(command)
    if executable is None:
        raise FileNotFoundError(f"Command is not installed or not on PATH: {command}")

    if os.name == "nt" and Path(executable).suffix.lower() in {".cmd", ".bat"}:
        if command not in {"npm", "npx"}:
            raise ValueError("Batch-file commands are disabled.")

        node = shutil.which("node")
        if node is None or Path(node).suffix.lower() in {".cmd", ".bat"}:
            raise FileNotFoundError("A native Node.js executable is required.")

        cli_name = f"{command}-cli.js"
        npm_cli = (
            Path(executable).parent
            / "node_modules"
            / "npm"
            / "bin"
            / cli_name
        )
        if not npm_cli.is_file():
            raise FileNotFoundError(
                f"Could not locate npm's native CLI script: {npm_cli}"
            )
        return [node, str(npm_cli)]

    return [executable]


def _truncate_output(output):
    if len(output) <= MAX_OUTPUT_SIZE:
        return output
    return output[:MAX_OUTPUT_SIZE] + "\n[Output truncated]"


def run_command(command, args, cwd=".", timeout=60):
    """Run an approved development command in a workspace directory."""
    if not isinstance(command, str) or command.lower() not in ALLOWED_COMMANDS:
        raise ValueError(
            f"Command must be one of: {', '.join(sorted(ALLOWED_COMMANDS))}."
        )
    command = command.lower()

    if (
        not isinstance(args, list)
        or len(args) > MAX_ARGUMENTS
        or any(
            not isinstance(argument, str)
            or "\0" in argument
            or len(argument) > MAX_ARGUMENT_LENGTH
            for argument in args
        )
    ):
        raise ValueError(
            f"args must be a list of at most {MAX_ARGUMENTS} strings, "
            f"each no longer than {MAX_ARGUMENT_LENGTH} characters."
        )

    finite_timeout = False
    if isinstance(timeout, (int, float)) and not isinstance(timeout, bool):
        try:
            finite_timeout = math.isfinite(timeout)
        except OverflowError:
            pass

    if not finite_timeout or timeout <= 0 or timeout > MAX_TIMEOUT_SECONDS:
        raise ValueError(
            f"timeout must be between 0 and {MAX_TIMEOUT_SECONDS} seconds."
        )

    working_directory, relative_cwd = _resolve_working_directory(cwd)
    executable = _resolve_executable(command)
    result = subprocess.run(
        [*executable, *args],
        cwd=str(working_directory),
        shell=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
        check=False,
    )

    return {
        "command": command,
        "args": args,
        "cwd": relative_cwd,
        "exit_code": result.returncode,
        "stdout": _truncate_output(result.stdout),
        "stderr": _truncate_output(result.stderr),
    }
