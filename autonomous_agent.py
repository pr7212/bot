"""
Apply the JARVIS updates to your repository safely.

Put this script in the SAME folder as the downloaded files:

    jarvis_modular.py      -> autonomous_agent.py
    workspace_fixed.py     -> tools/workspace.py
    computer_hardened.py   -> tools/computer.py
    screen_fixed.py        -> tools/screen.py

Usage:
    python apply_updates.py C:\\path\\to\\bot            (dry run: changes nothing)
    python apply_updates.py C:\\path\\to\\bot --apply    (backs up, then applies)

What --apply does:
  1. Copies every file it is about to replace into
     <repo>/archive/pre_update_<timestamp>/ (same relative paths).
  2. Writes the new files.
  3. Patches tools/terminal.py so truncated output keeps the END of the
     output (where tracebacks and test summaries are), not just the start.
  4. Adds projects/, screenshots/ and database/ to .gitignore.
  5. Checks that every resulting Python file at least compiles.

It never deletes anything and never touches files other than those above.
"""

import argparse
import shutil
import sys

from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent

# downloaded file -> destination inside the repository
FILES = {
    "jarvis_modular.py": "autonomous_agent.py",
    "workspace_fixed.py": "tools/workspace.py",
    "computer_hardened.py": "tools/computer.py",
    "screen_fixed.py": "tools/screen.py",
}

GITIGNORE_LINES = ["projects/", "screenshots/", "database/"]

OLD_TRUNCATE = (
    r'''def _truncate_output(output):
    if len(output) <= MAX_OUTPUT_SIZE:
        return output
    return output[:MAX_OUTPUT_SIZE] + "\n[Output truncated]"
'''
)

NEW_TRUNCATE = (
    r'''def _truncate_output(output):
    if len(output) <= MAX_OUTPUT_SIZE:
        return output
    head = MAX_OUTPUT_SIZE // 3
    tail = MAX_OUTPUT_SIZE - head
    return output[:head] + "\n[... output truncated ...]\n" + output[-tail:]
'''
)


def read_text(path):
    """Read a file, remembering whether it used Windows line endings."""
    raw = path.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    return raw.replace("\r\n", "\n"), crlf


def write_text(path, text, crlf):
    if crlf:
        text = text.replace("\n", "\r\n")
    path.write_bytes(text.encode("utf-8"))


def plan_terminal_patch(repo):
    """Return (status, new_text, crlf) for tools/terminal.py."""
    path = repo / "tools" / "terminal.py"

    if not path.exists():
        return "missing", None, False

    text, crlf = read_text(path)

    if "[... output truncated ...]" in text:
        return "already patched", None, crlf

    if OLD_TRUNCATE not in text:
        return "not recognised (apply by hand)", None, crlf

    return "will patch", text.replace(OLD_TRUNCATE, NEW_TRUNCATE), crlf


def plan_gitignore(repo):
    path = repo / ".gitignore"

    if path.exists():
        text, crlf = read_text(path)
    else:
        text, crlf = "", False

    existing = {line.strip().rstrip("/") for line in text.splitlines()}
    missing = [l for l in GITIGNORE_LINES if l.rstrip("/") not in existing]

    if not missing:
        return [], None, crlf

    prefix = "" if (not text or text.endswith("\n")) else "\n"
    return missing, text + prefix + "\n".join(missing) + "\n", crlf


def main():
    parser = argparse.ArgumentParser(description="Apply JARVIS updates safely.")
    parser.add_argument("repo", help="path to your bot repository (the folder with tools/ and agent/)")
    parser.add_argument("--apply", action="store_true", help="actually make the changes (default is a dry run)")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()

    # ---- sanity checks -----------------------------------------------------
    problems = []

    if not (repo / "tools" / "terminal.py").is_file():
        problems.append(f"{repo} does not look like the bot repository (no tools/terminal.py).")

    if not (repo / "agent" / "memory.py").is_file():
        problems.append(f"{repo} does not look like the bot repository (no agent/memory.py).")

    missing_sources = [name for name in FILES if not (HERE / name).is_file()]

    if missing_sources:
        problems.append(
            "Missing downloaded files next to this script: " + ", ".join(missing_sources)
        )

    for name in FILES:
        source = HERE / name

        if source.is_file():
            try:
                compile(source.read_text(encoding="utf-8"), str(source), "exec")
            except SyntaxError as error:
                problems.append(f"{name} has a syntax error: {error}")

    if problems:
        print("Cannot continue:")
        for problem in problems:
            print("  -", problem)
        return 1

    # ---- plan --------------------------------------------------------------
    print(f"Repository: {repo}")
    print("Mode:", "APPLY" if args.apply else "DRY RUN (nothing will be changed)")
    print()

    actions = []

    for name, destination in FILES.items():
        source = HERE / name
        target = repo / destination

        if not target.exists():
            status = "new file"
        elif target.read_bytes() == source.read_bytes():
            status = "identical (skipped)"
        else:
            status = "will replace (original is backed up)"

        print(f"  {name:<22} -> {destination:<26} {status}")
        actions.append((source, target, destination, status))

    terminal_status, terminal_text, terminal_crlf = plan_terminal_patch(repo)
    print(f"  {'(patch)':<22} -> {'tools/terminal.py':<26} {terminal_status}")

    ignore_missing, ignore_text, ignore_crlf = plan_gitignore(repo)
    print(
        f"  {'(append)':<22} -> {'.gitignore':<26} "
        + (("add " + ", ".join(ignore_missing)) if ignore_missing else "already complete")
    )

    if not args.apply:
        print("\nDry run only. Re-run with --apply to make these changes.")
        return 0

    # ---- apply -------------------------------------------------------------
    backup_root = repo / "archive" / f"pre_update_{datetime.now():%Y%m%d_%H%M%S}"
    backed_up = []

    def backup(path):
        relative = path.relative_to(repo)
        destination = backup_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        backed_up.append(str(relative))

    for source, target, destination, status in actions:
        if status.startswith("identical"):
            continue

        if target.exists():
            backup(target)

        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    if terminal_text is not None:
        backup(repo / "tools" / "terminal.py")
        write_text(repo / "tools" / "terminal.py", terminal_text, terminal_crlf)

    if ignore_text is not None:
        if (repo / ".gitignore").exists():
            backup(repo / ".gitignore")

        write_text(repo / ".gitignore", ignore_text, ignore_crlf)

    # ---- verify --------------------------------------------------------------
    failed = []

    for destination in list(FILES.values()) + ["tools/terminal.py"]:
        path = repo / destination

        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except SyntaxError as error:
            failed.append(f"{destination}: {error}")

    print()

    if backed_up:
        print(f"Backed up {len(backed_up)} file(s) to {backup_root}")

    if failed:
        print("WARNING: these files do not compile:")
        for line in failed:
            print("  -", line)
        print("Restore them from the backup folder above.")
        return 1

    print("Done. All files compile.")
    print()
    print("Next steps:")
    print("  1. pip install pyautogui pillow pygetwindow pyperclip ollama")
    print('  2. python -c "from tools import computer, screen, terminal, workspace; print(\'tools OK\')"')
    print("  3. python -m tools.screen calibrate    (needs Ollama + qwen3-vl:4b running)")
    print("  4. python autonomous_agent.py          (first task: add two numbers, write a test, run it)")
    print("  5. Check `git log` in your bot repo: there should be NO commits starting with 'jarvis:'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
