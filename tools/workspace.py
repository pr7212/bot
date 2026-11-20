import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
BACKUP_DIR = WORKSPACE / ".jarvis_backups"

MAX_FILE_SIZE = 50_000
MAX_OUTPUT_SIZE = 12_000
TIMEOUT_SECONDS = 60

IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".jarvis_backups",
    ".agent_backups",
}


def safe_path(filename):
    """Resolve a path and prevent access outside the workspace."""
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("A valid filename is required.")

    target = (WORKSPACE / filename).resolve()

    try:
        target.relative_to(WORKSPACE.resolve())
    except ValueError:
        raise ValueError("Access outside the JARVIS workspace is forbidden.")

    if target == WORKSPACE:
        raise ValueError("A filename is required, not the workspace root.")

    if any(part in IGNORED_DIRS for part in target.relative_to(WORKSPACE).parts):
        raise ValueError("Access to this directory is restricted.")

    return target


def list_files():
    """List project files while excluding dependency and backup folders."""
    files = []

    for path in WORKSPACE.rglob("*"):
        if not path.is_file():
            continue

        if any(part in IGNORED_DIRS for part in path.relative_to(WORKSPACE).parts):
            continue

        files.append(str(path.relative_to(WORKSPACE)))

        if len(files) >= 200:
            break

    return files


def read_file(filename):
    """Read a project file."""
    path = safe_path(filename)

    if not path.is_file():
        raise FileNotFoundError(f"File not found: {filename}")

    if path.stat().st_size > MAX_FILE_SIZE:
        raise ValueError("File is too large to read.")

    return path.read_text(encoding="utf-8")


def backup_file(path):
    """Back up an existing file before modifying it."""
    if not path.exists():
        return None

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    relative = path.relative_to(WORKSPACE)
    backup_path = BACKUP_DIR / relative
    backup_path.parent.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = backup_path.with_name(
        f"{backup_path.stem}_{timestamp}{backup_path.suffix}"
    )

    shutil.copy2(path, backup_path)

    return str(backup_path)


def write_file(filename, content):
    """Create or update a project file, backing up existing content."""
    if not isinstance(content, str):
        raise TypeError("File content must be text.")

    if len(content.encode("utf-8")) > MAX_FILE_SIZE:
        raise ValueError("File content exceeds the size limit.")

    path = safe_path(filename)

    if path.exists() and not path.is_file():
        raise ValueError("Target must be a file.")

    backup = backup_file(path)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

    return {
        "message": f"File saved: {filename}",
        "backup": backup,
    }


def run_python_file(filename):
    """Execute a Python file inside the workspace."""
    path = safe_path(filename)

    if path.suffix.lower() != ".py":
        raise ValueError("Only Python files can be executed by this tool.")

    if not path.is_file():
        raise FileNotFoundError(f"Python file not found: {filename}")

    result = subprocess.run(
        [sys.executable, str(path)],
        cwd=str(WORKSPACE),
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
        errors="replace",
    )

    output = (
        f"Exit code: {result.returncode}\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )

    if len(output) > MAX_OUTPUT_SIZE:
        output = output[:MAX_OUTPUT_SIZE] + "\n[Output truncated]"

    return output


if __name__ == "__main__":
    print("JARVIS WORKSPACE TOOLS")
    print("----------------------")
    print("Workspace:", WORKSPACE)
    print("\nProject files:")

    for filename in list_files():
        print("-", filename)
