
import subprocess
import sys
from pathlib import Path

TIMEOUT_SECONDS = 60
MAX_OUTPUT_CHARACTERS = 12000


def run_python(filename, workspace):
    workspace = Path(workspace).resolve()

    try:
        target = (workspace / filename).resolve()
        target.relative_to(workspace)

    except ValueError:
        print("Access denied: file is outside the workspace.")
        return

    except OSError as error:
        print(f"Path error: {error}")
        return

    if not target.exists() or not target.is_file():
        print("Python file does not exist.")
        return

    if target.suffix.lower() != ".py":
        print("Only Python files can be executed.")
        return

    print("\n========== EXECUTION PREVIEW ==========")
    print(f"File: {target.relative_to(workspace)}")
    print(f"Timeout: {TIMEOUT_SECONDS} seconds")
    print("=======================================")

    approval = input(
        "\nAllow execution? (yes/no): "
    ).strip().lower()

    if approval not in ("yes", "y"):
        print("Execution cancelled.")
        return

    try:
        result = subprocess.run(
            [sys.executable, "-u", str(target)],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_SECONDS,
            shell=False
        )

        output = result.stdout or ""
        errors = result.stderr or ""

        print("\n========== PROGRAM OUTPUT ==========")
        print(output or "(No standard output)")

        if errors:
            print("\n========== ERRORS ==========")
            print(errors)

        print("\nExit code:", result.returncode)
        print("Status:", "SUCCESS" if result.returncode == 0 else "FAILED")

        return {
            "success": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": output[:MAX_OUTPUT_CHARACTERS],
            "stderr": errors[:MAX_OUTPUT_CHARACTERS]
        }

    except subprocess.TimeoutExpired:
        print("Execution timed out.")
        return {
            "success": False,
            "exit_code": None,
            "stdout": "",
            "stderr": "Execution timed out."
        }

    except Exception as error:
        print("Execution error:", error)
        return {
            "success": False,
            "exit_code": None,
            "stdout": "",
            "stderr": str(error)
        }
