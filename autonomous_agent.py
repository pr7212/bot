import os
import shutil
import subprocess
import tempfile
import ctypes
import json

from pathlib import Path

import ollama

from tools import computer
from tools import screen
from tools import terminal

try:
    import pyautogui
    pyautogui.FAILSAFE = True   # slam mouse into a corner to abort
except Exception:
    pass


# ==========================================
# CONFIGURATION
# ==========================================

MODEL = "qwen3:8b"

PROJECT_DIR = (
    Path(__file__).resolve().parent
    / "projects"
    / "agent-test"
).resolve()

PLAN_FILE = PROJECT_DIR / "PLAN.md"
STOP_FILE = PROJECT_DIR / ".jarvis_stop"

NUM_CTX = 16384            # raise if your VRAM allows
NUM_PREDICT = 3000

MAX_STEPS = 30
MAX_TOOL_CALLS = 80
MAX_FILE_SIZE = 50_000
MAX_OUTPUT_SIZE = 8_000    # applied to what the MODEL sees, not just display
MAX_TIMEOUT = 120

# Old tool results get squeezed once history passes this many characters
# (roughly 4 chars per token, leaving room for the system prompt + tools).
MAX_HISTORY_CHARS = 36_000

MAX_REPEATED_CALLS = 3     # identical call with no file changes in between
MAX_VERIFY_NAGS = 2        # times we push back on "done" without a passing run

# Generate a PLAN.md checklist (with thinking enabled) for new tasks.
AUTO_PLAN = True

# File changes inside the isolated project are automatic (git is the undo).
AUTO_APPROVE_FILE_CHANGES = True

# Commands can execute arbitrary code (python -c, node -e, npm scripts).
# Keep approval enabled until JARVIS runs in a dedicated, isolated VM.
AUTO_APPROVE_COMMANDS = False

# Typing and hotkeys can do real damage on the real desktop.
AUTO_APPROVE_DESKTOP_INPUT = False

# Enable actual mouse and keyboard control explicitly:
# PowerShell: $env:JARVIS_ENABLE_DESKTOP="1"
ENABLE_DESKTOP_CONTROL = (
    os.getenv("JARVIS_ENABLE_DESKTOP", "0") == "1"
)

ALLOWED_COMMANDS = {"python", "node", "npm", "npx", "git", "php"}

IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".agent_backups",
}

FILE_CHANGE_TOOLS = {"create_file", "update_file", "edit_file"}


# ==========================================
# WINDOWS KEEP-AWAKE
# ==========================================

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002


def keep_awake():
    """Prevent Windows from sleeping while JARVIS works."""
    if os.name != "nt":
        return

    ctypes.windll.kernel32.SetThreadExecutionState(
        ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
    )


def allow_sleep():
    """Restore normal Windows power management."""
    if os.name != "nt":
        return

    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)


# ==========================================
# HELPERS: SAFETY, PATHS, OUTPUT
# ==========================================

def approve(message):
    print("\n" + message)
    answer = input("Approve? (yes/no): ").strip().lower()
    return answer in ("yes", "y")


def check_stop():
    if STOP_FILE.exists():
        raise KeyboardInterrupt("Emergency stop file detected.")


def clip(text, limit=MAX_OUTPUT_SIZE):
    """Truncate long output but keep the tail, where errors usually are."""
    text = str(text)

    if len(text) <= limit:
        return text

    head = limit // 3
    tail = limit - head

    return (
        text[:head]
        + f"\n...[{len(text) - limit} characters truncated]...\n"
        + text[-tail:]
    )


def safe_path(filename):
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("Invalid filename.")

    path = (PROJECT_DIR / filename).resolve()

    try:
        relative = path.relative_to(PROJECT_DIR)
    except ValueError:
        raise ValueError("Access outside the project is forbidden.")

    if path == PROJECT_DIR:
        raise ValueError("Cannot operate on project root.")

    if any(part in IGNORED_DIRS for part in relative.parts):
        raise ValueError("Access to protected directories is forbidden.")

    return path


def safe_cwd(sub="."):
    """Resolve a working directory and guarantee it is inside the project."""
    if not isinstance(sub, str) or not sub.strip():
        sub = "."

    # Models often pass "projects/agent-test" or an absolute path;
    # normalise those back to the project root.
    candidate = Path(sub)

    if not candidate.is_absolute():
        candidate = PROJECT_DIR / candidate

    path = candidate.resolve()

    try:
        path.relative_to(PROJECT_DIR)
    except ValueError:
        # Fall back to treating it as relative to the project root.
        path = (PROJECT_DIR / Path(sub).name).resolve()
        try:
            path.relative_to(PROJECT_DIR)
        except ValueError:
            raise ValueError("Working directory must be inside the project.")

    if not path.is_dir():
        raise ValueError(f"Working directory does not exist: {sub}")

    return path


# ==========================================
# GIT CHECKPOINTS (undo for everything)
# ==========================================

GIT = shutil.which("git")


def _git(*args, timeout=30):
    return subprocess.run(
        [GIT, *args],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def init_git():
    if not GIT:
        print("WARNING: git not found. No checkpoints will be created.")
        return

    if not (PROJECT_DIR / ".git").exists():
        _git("init")

    gitignore = PROJECT_DIR / ".gitignore"

    if not gitignore.exists():
        gitignore.write_text(
            "node_modules/\n.venv/\nvenv/\n__pycache__/\n"
            ".agent_backups/\n.jarvis_stop\n*.tmp\n",
            encoding="utf-8",
        )


def checkpoint(message):
    """Commit everything if anything changed. Never raises."""
    if not GIT:
        return None

    try:
        _git("add", "-A")

        status = _git("status", "--porcelain")

        if not status.stdout.strip():
            return None

        result = _git(
            "-c", "user.name=JARVIS",
            "-c", "user.email=jarvis@localhost",
            "commit", "-m", f"jarvis: {message}",
        )

        return result.stdout.strip().splitlines()[0] if result.stdout else None

    except Exception as error:
        print(f"(checkpoint failed: {error})")
        return None


# ==========================================
# FILE TOOLS
# ==========================================

def list_files():
    results = []

    for root, dirs, files in os.walk(PROJECT_DIR):
        check_stop()

        # Prune in place so we never descend into node_modules, .git, etc.
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]

        for name in files:
            full = Path(root) / name
            results.append(str(full.relative_to(PROJECT_DIR)))

            if len(results) >= 200:
                results.append("...[list truncated at 200 files]")
                return "\n".join(results)

    return "\n".join(sorted(results)) or "Project is empty."


def read_file(filename):
    path = safe_path(filename)

    if not path.is_file():
        raise ValueError("File does not exist.")

    if path.stat().st_size > MAX_FILE_SIZE:
        raise ValueError(
            "File exceeds the read size limit. "
            "Ask for a smaller file or inspect it with run_command."
        )

    return path.read_text(encoding="utf-8", errors="replace")


def create_file(filename, content):
    path = safe_path(filename)

    if not isinstance(content, str):
        raise ValueError("Content must be text.")

    if len(content.encode("utf-8")) > MAX_FILE_SIZE:
        raise ValueError(
            "File exceeds the size limit. Create a short skeleton, "
            "then add sections with edit_file."
        )

    if path.exists():
        raise ValueError("File already exists. Use edit_file or update_file.")

    if not AUTO_APPROVE_FILE_CHANGES:
        if not approve(f"CREATE FILE: {filename}"):
            return "Creation rejected."

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("x", encoding="utf-8", newline="\n") as file:
        file.write(content)

    return f"Created {filename}."


def _atomic_write(path, content):
    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_file.write(content)
            temp_path = Path(temp_file.name)

        os.replace(temp_path, path)

    except Exception:
        if temp_path and temp_path.exists():
            temp_path.unlink()
        raise


def update_file(filename, content):
    """Replace a whole file. Prefer edit_file for small changes."""
    path = safe_path(filename)

    if not path.is_file():
        raise ValueError("File does not exist.")

    if not isinstance(content, str):
        raise ValueError("Content must be text.")

    if len(content.encode("utf-8")) > MAX_FILE_SIZE:
        raise ValueError("File exceeds the size limit.")

    if not AUTO_APPROVE_FILE_CHANGES:
        if not approve(f"UPDATE FILE: {filename}"):
            return "Update rejected."

    # Safety net: commit the previous state so any rewrite is reversible.
    checkpoint(f"before rewriting {filename}")

    _atomic_write(path, content)

    return f"Updated {filename}."


def edit_file(filename, old, new):
    """Replace one exact snippet. Safer than rewriting the whole file."""
    path = safe_path(filename)

    if not path.is_file():
        raise ValueError("File does not exist.")

    if not isinstance(old, str) or not old:
        raise ValueError("'old' must be a non-empty string.")

    if not isinstance(new, str):
        raise ValueError("'new' must be a string.")

    text = path.read_text(encoding="utf-8")
    count = text.count(old)

    if count == 0:
        raise ValueError(
            "'old' text was not found. Use read_file and copy it exactly, "
            "including whitespace."
        )

    if count > 1:
        raise ValueError(
            f"'old' text matched {count} times; include more surrounding "
            "lines so it matches exactly once."
        )

    updated = text.replace(old, new)

    if len(updated.encode("utf-8")) > MAX_FILE_SIZE:
        raise ValueError("Result would exceed the file size limit.")

    if not AUTO_APPROVE_FILE_CHANGES:
        if not approve(f"EDIT FILE: {filename}"):
            return "Edit rejected."

    _atomic_write(path, updated)

    return f"Edited {filename}."


# ==========================================
# TERMINAL TOOLS
# ==========================================

def run_development_command(command, args, cwd=".", timeout=60):
    check_stop()

    if not isinstance(command, str) or command not in ALLOWED_COMMANDS:
        raise ValueError(
            f"Command not allowed. Allowed: {', '.join(sorted(ALLOWED_COMMANDS))}"
        )

    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise ValueError("'args' must be a list of strings.")

    try:
        timeout = int(timeout)
    except (TypeError, ValueError):
        timeout = 60

    timeout = max(1, min(timeout, MAX_TIMEOUT))

    work_dir = safe_cwd(cwd)

    description = (
        f"COMMAND: {command} {' '.join(args)}\n"
        f"WORKING DIRECTORY: {work_dir}\n"
        f"TIMEOUT: {timeout} seconds"
    )

    if not AUTO_APPROVE_COMMANDS:
        if not approve(description):
            return "Command rejected by user."

    result = terminal.run_command(
        command=command,
        args=args,
        cwd=str(work_dir),
        timeout=timeout,
    )

    return json.dumps(result, indent=2, default=str)


def run_python(filename):
    path = safe_path(filename)

    if path.suffix.lower() != ".py":
        raise ValueError("Only Python scripts can be executed.")

    if not path.is_file():
        raise ValueError("Python file does not exist.")

    return run_development_command(
        "python",
        [str(path.relative_to(PROJECT_DIR))],
        ".",
        MAX_TIMEOUT,
    )


def command_succeeded(result_text):
    """
    Decide whether a command result means success.
    Adjust the key names here to match what tools/terminal.py returns.
    """
    try:
        data = json.loads(result_text)
    except (TypeError, ValueError):
        return False

    if not isinstance(data, dict):
        return False

    for key in ("returncode", "return_code", "exit_code", "exitcode"):
        if key in data:
            return data[key] == 0

    for key in ("success", "ok"):
        if key in data:
            return bool(data[key])

    return False


def counts_as_verification(name, arguments):
    """Only runs that actually exercise the code can clear the dirty flag."""
    if name == "run_python":
        return True

    if name == "run_command":
        command = arguments.get("command")
        args = arguments.get("args") or []

        if command == "git":
            return False

        if command in ("npm", "npx") and args and args[0] in (
            "install", "i", "ci", "init", "config", "cache"
        ):
            return False

        return command in ALLOWED_COMMANDS

    return False


# ==========================================
# COMPUTER CONTROL
# ==========================================

def require_desktop():
    if not ENABLE_DESKTOP_CONTROL:
        raise PermissionError(
            "Desktop control is disabled. "
            "Set JARVIS_ENABLE_DESKTOP=1 in PowerShell "
            "and restart JARVIS."
        )

    check_stop()


def desktop_move(x, y, duration=0.3):
    require_desktop()
    return computer.move_mouse(x, y, duration)


def desktop_click(x, y):
    require_desktop()
    return computer.click_mouse(x, y)


def desktop_right_click(x, y):
    require_desktop()
    return computer.right_click_mouse(x, y)


def desktop_double_click(x, y):
    require_desktop()
    return computer.double_click_mouse(x, y)


def desktop_scroll(clicks):
    require_desktop()
    return computer.scroll_mouse(clicks)


def desktop_drag(start_x, start_y, end_x, end_y):
    require_desktop()
    return computer.drag_mouse(start_x, start_y, end_x, end_y)


def desktop_type(text):
    require_desktop()

    if not isinstance(text, str):
        raise ValueError("Text must be a string.")

    if len(text) > 5000:
        raise ValueError("Typing request exceeds 5000 characters.")

    if not AUTO_APPROVE_DESKTOP_INPUT:
        preview = text if len(text) <= 200 else text[:200] + "..."
        if not approve(f"TYPE TEXT ON REAL DESKTOP:\n{preview}"):
            return "Typing rejected by user."

    return computer.type_text(text)


def desktop_key(key):
    require_desktop()
    return computer.press_key(key)


def desktop_hotkey(keys):
    require_desktop()

    if not AUTO_APPROVE_DESKTOP_INPUT:
        if not approve(f"PRESS HOTKEY ON REAL DESKTOP: {'+'.join(keys)}"):
            return "Hotkey rejected by user."

    return computer.press_hotkey(keys)


def desktop_screenshot():
    require_desktop()
    return computer.take_screenshot()


def desktop_analyze():
    require_desktop()
    return json.dumps(screen.analyze_screen(), indent=2, default=str)


def desktop_open_notepad():
    require_desktop()
    return computer.open_notepad()


def desktop_screen_size():
    require_desktop()
    return json.dumps(computer.get_screen_size())


# ==========================================
# TOOL DEFINITIONS
# ==========================================

def tool(name, description, properties=None, required=None):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": required or [],
            },
        },
    }


TOOLS = [

    # FILESYSTEM

    tool("list_files", "List project files."),

    tool(
        "read_file",
        "Read a project file.",
        {"filename": {"type": "string"}},
        ["filename"],
    ),

    tool(
        "create_file",
        "Create a NEW file inside the project. Never overwrites. "
        "For large files create a short skeleton, then extend it with edit_file.",
        {
            "filename": {"type": "string"},
            "content": {"type": "string"},
        },
        ["filename", "content"],
    ),

    tool(
        "edit_file",
        "PREFERRED way to change an existing file. Replaces one exact "
        "snippet ('old') with 'new'. 'old' must match exactly once.",
        {
            "filename": {"type": "string"},
            "old": {"type": "string"},
            "new": {"type": "string"},
        },
        ["filename", "old", "new"],
    ),

    tool(
        "update_file",
        "Rewrite an entire existing file. Use only for small files or "
        "full rewrites; prefer edit_file.",
        {
            "filename": {"type": "string"},
            "content": {"type": "string"},
        },
        ["filename", "content"],
    ),

    # EXECUTION

    tool(
        "run_python",
        "Execute a Python script in the isolated project.",
        {"filename": {"type": "string"}},
        ["filename"],
    ),

    tool(
        "run_command",
        "Run python, node, npm, npx, git or php in the project workspace. "
        "Command execution requires approval. cwd is relative to the "
        "project root (use '.' for the root).",
        {
            "command": {"type": "string"},
            "args": {"type": "array", "items": {"type": "string"}},
            "cwd": {"type": "string"},
            "timeout": {"type": "integer"},
        },
        ["command", "args"],
    ),

    # SCREEN AND VISION

    tool(
        "get_screen_size",
        "Get desktop dimensions. Requires desktop control enabled.",
    ),

    tool(
        "take_screenshot",
        "Capture the current desktop. Requires desktop control enabled.",
    ),

    tool(
        "analyze_screen",
        "Use Qwen3-VL to inspect the desktop and identify visible "
        "interface elements. Requires desktop control enabled.",
    ),

    # MOUSE

    tool(
        "move_mouse",
        "Move the mouse to screen coordinates.",
        {
            "x": {"type": "integer"},
            "y": {"type": "integer"},
            "duration": {"type": "number"},
        },
        ["x", "y"],
    ),

    tool(
        "click_mouse",
        "Click at screen coordinates.",
        {"x": {"type": "integer"}, "y": {"type": "integer"}},
        ["x", "y"],
    ),

    tool(
        "right_click_mouse",
        "Right-click at screen coordinates.",
        {"x": {"type": "integer"}, "y": {"type": "integer"}},
        ["x", "y"],
    ),

    tool(
        "double_click_mouse",
        "Double-click at screen coordinates.",
        {"x": {"type": "integer"}, "y": {"type": "integer"}},
        ["x", "y"],
    ),

    tool(
        "scroll_mouse",
        "Scroll the desktop vertically.",
        {"clicks": {"type": "integer"}},
        ["clicks"],
    ),

    tool(
        "drag_mouse",
        "Drag the mouse between screen coordinates.",
        {
            "start_x": {"type": "integer"},
            "start_y": {"type": "integer"},
            "end_x": {"type": "integer"},
            "end_y": {"type": "integer"},
        },
        ["start_x", "start_y", "end_x", "end_y"],
    ),

    # KEYBOARD

    tool(
        "type_text",
        "Type text into the currently focused application.",
        {"text": {"type": "string"}},
        ["text"],
    ),

    tool(
        "press_key",
        "Press one keyboard key.",
        {"key": {"type": "string"}},
        ["key"],
    ),

    tool(
        "press_hotkey",
        "Press a keyboard shortcut, for example ctrl+s.",
        {"keys": {"type": "array", "items": {"type": "string"}}},
        ["keys"],
    ),

    tool("open_notepad", "Open Windows Notepad."),
]


# ==========================================
# TOOL DISPATCHER
# ==========================================

DISPATCH = {
    "list_files": lambda a: list_files(),

    "read_file": lambda a: read_file(a["filename"]),

    "create_file": lambda a: create_file(a["filename"], a["content"]),

    "edit_file": lambda a: edit_file(a["filename"], a["old"], a["new"]),

    "update_file": lambda a: update_file(a["filename"], a["content"]),

    "run_python": lambda a: run_python(a["filename"]),

    "run_command": lambda a: run_development_command(
        a["command"],
        a["args"],
        a.get("cwd", "."),
        a.get("timeout", 60),
    ),

    "get_screen_size": lambda a: desktop_screen_size(),

    "take_screenshot": lambda a: desktop_screenshot(),

    "analyze_screen": lambda a: desktop_analyze(),

    "move_mouse": lambda a: desktop_move(
        a["x"], a["y"], a.get("duration", 0.3)
    ),

    "click_mouse": lambda a: desktop_click(a["x"], a["y"]),

    "right_click_mouse": lambda a: desktop_right_click(a["x"], a["y"]),

    "double_click_mouse": lambda a: desktop_double_click(a["x"], a["y"]),

    "scroll_mouse": lambda a: desktop_scroll(a["clicks"]),

    "drag_mouse": lambda a: desktop_drag(
        a["start_x"], a["start_y"], a["end_x"], a["end_y"]
    ),

    "type_text": lambda a: desktop_type(a["text"]),

    "press_key": lambda a: desktop_key(a["key"]),

    "press_hotkey": lambda a: desktop_hotkey(a["keys"]),

    "open_notepad": lambda a: desktop_open_notepad(),
}


def execute_tool(name, arguments):
    if not isinstance(arguments, dict):
        return "Error: Tool arguments must be an object."

    try:
        check_stop()

        if name not in DISPATCH:
            return f"Unknown tool: {name}. Available: {', '.join(DISPATCH)}"

        return str(DISPATCH[name](arguments))

    except KeyboardInterrupt:
        raise

    except KeyError as error:
        return (
            f"Tool error: missing required argument {error}. "
            f"Call {name} again with all required arguments."
        )

    except Exception as error:
        return f"Tool error: {type(error).__name__}: {error}"


# ==========================================
# CONTEXT MANAGEMENT
# ==========================================

def message_size(message):
    if isinstance(message, dict):
        return len(str(message.get("content", "")))

    return len(str(getattr(message, "content", "") or "")) + len(
        str(getattr(message, "tool_calls", "") or "")
    )


def compact_history(messages, keep_recent=6):
    """
    When the conversation gets long, shrink OLD tool results.
    The system prompt, the task, and recent messages stay intact.
    """
    total = sum(message_size(m) for m in messages)

    if total <= MAX_HISTORY_CHARS:
        return

    cutoff = len(messages) - keep_recent

    for index, message in enumerate(messages):
        if index < 2 or index >= cutoff:
            continue

        if isinstance(message, dict) and message.get("role") == "tool":
            content = str(message.get("content", ""))

            if len(content) > 600:
                message["content"] = (
                    content[:250]
                    + "\n...[old output removed to save context]...\n"
                    + content[-250:]
                )

        total = sum(message_size(m) for m in messages)

        if total <= MAX_HISTORY_CHARS:
            break


# ==========================================
# PLAN FILE (resumable work)
# ==========================================

def plan_has_open_items():
    if not PLAN_FILE.exists():
        return False

    return "[ ]" in PLAN_FILE.read_text(encoding="utf-8", errors="replace")


def archive_plan():
    if PLAN_FILE.exists():
        target = PLAN_FILE.with_name("PLAN.old.md")
        os.replace(PLAN_FILE, target)


def generate_plan(instruction):
    """One thinking-enabled call to produce a short checklist."""
    print("\nJARVIS is planning...")

    try:
        response = ollama.chat(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior software engineer. Produce a "
                        "markdown checklist of 4-12 small, concrete, "
                        "verifiable steps. Each line must look like "
                        "'- [ ] step'. The final steps must be running "
                        "tests/the app and fixing failures. Output ONLY "
                        "the checklist."
                    ),
                },
                {"role": "user", "content": instruction},
            ],
            think=True,
            keep_alive="10m",
            options={"temperature": 0.3, "num_ctx": NUM_CTX, "num_predict": 1500},
        )

        text = (response.message.content or "").strip()

        if "[ ]" not in text:
            return None

        PLAN_FILE.write_text(
            f"# Task\n{instruction}\n\n# Plan\n{text}\n",
            encoding="utf-8",
        )

        print(text)
        return text

    except Exception as error:
        print(f"(planning skipped: {type(error).__name__}: {error})")
        return None


# ==========================================
# AUTONOMOUS AGENT LOOP
# ==========================================

SYSTEM_PROMPT = """
You are JARVIS, an autonomous local software engineering
and computer-use agent.

YOUR WORKSPACE:
The current project directory is your coding workspace.
Use filesystem tools to inspect and modify it.

YOUR OBJECTIVE:
Complete the user's task, not merely explain how to do it.

WORKFLOW:
1. Read PLAN.md (if present) and list_files to see current state.
2. Work on ONE unchecked plan item at a time.
3. Implement it in small pieces.
4. Run the code or tests to verify it.
5. Read errors carefully, fix the cause, run again.
6. Mark finished items by changing '[ ]' to '[x]' in PLAN.md using edit_file.
7. When everything is verified, give a short final report: what was done,
   how it was verified, and what remains.

CODING RULES:
- Prefer edit_file for changes to existing files. Use update_file only for
  small files or full rewrites.
- Keep each file reasonably small. For big files, create a skeleton and
  extend it with edit_file.
- Preserve existing user files. Never overwrite unnecessarily.
- Always read a file before editing it.
- Never claim something works without running it and seeing it pass.

COMPUTER RULES:
- Prefer terminal and file tools over mouse and keyboard. Use the desktop
  only when a task truly needs a GUI.
- Use analyze_screen before interacting with unfamiliar interfaces.
- Do not guess screen coordinates.
- Mouse and keyboard actions affect the real desktop.
- Never interact with password fields, payment screens,
  or account-security settings.
- Do not send messages, submit forms, purchase items,
  or delete user data without explicit authorization.
- Do not repeatedly click when an action has uncertain results.

EXECUTION RULES:
- Use the project directory for development. cwd is relative to it.
- Do not access unrelated user files.
- Do not run destructive commands.
- Do not install software without user authorization.
- If a tool fails, read the error, and try a DIFFERENT approach.
  Never repeat an identical failing call.

IMPORTANT:
- Use actual structured tool calls.
- Do not pretend to execute tools or invent tool results.
- Continue working after successful intermediate steps.
- Stop and explain if you cannot safely continue.
"""


def run_agent(instruction):
    # ---- plan handling -------------------------------------------------
    plan_text = None

    if plan_has_open_items():
        print("\nAn unfinished plan exists in PLAN.md.")
        if approve("Resume the existing plan? (no = start fresh)"):
            plan_text = PLAN_FILE.read_text(encoding="utf-8", errors="replace")
        else:
            archive_plan()

    if plan_text is None and AUTO_PLAN:
        plan_text = generate_plan(instruction)

    system_content = SYSTEM_PROMPT

    if plan_text:
        system_content += (
            "\nCURRENT PLAN (also stored in PLAN.md; keep it updated):\n"
            + plan_text
        )

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": instruction},
    ]

    # ---- loop state ----------------------------------------------------
    total_calls = 0
    dirty = False            # files changed since last passing run
    nags = 0
    change_counter = 0       # bumps whenever a file changes
    call_counts = {}         # (name, args, change_counter) -> repeats

    for step in range(1, MAX_STEPS + 1):

        check_stop()

        print("\n" + "=" * 45)
        print(f"JARVIS STEP {step}/{MAX_STEPS}")
        print("=" * 45)

        compact_history(messages)

        try:
            response = ollama.chat(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                think=False,
                keep_alive="10m",
                options={
                    "temperature": 0,
                    "num_ctx": NUM_CTX,
                    "num_predict": NUM_PREDICT,
                },
            )
        except Exception as error:
            print(f"\nModel error: {type(error).__name__}: {error}")
            print("Is Ollama running and the model pulled?")
            return

        message = response.message
        messages.append(message)

        tool_calls = message.tool_calls or []

        # ---- model thinks it is finished ------------------------------
        if not tool_calls:

            if dirty and nags < MAX_VERIFY_NAGS:
                nags += 1
                print("\n(JARVIS tried to finish without verifying; "
                      "sending it back to test.)")
                messages.append({
                    "role": "user",
                    "content": (
                        "You changed files since your last passing run. "
                        "Run the tests or the program now, and fix any "
                        "failures before reporting."
                    ),
                })
                continue

            print("\nJARVIS:")
            print(message.content or "No final response was provided.")

            if dirty:
                print("\nNOTE: files changed after the last passing run; "
                      "the result may be unverified.")

            checkpoint("final state")
            return

        # ---- execute tool calls ---------------------------------------
        files_changed_this_step = False

        for call in tool_calls:

            check_stop()

            total_calls += 1

            if total_calls > MAX_TOOL_CALLS:
                print("Maximum tool-call limit reached.")
                checkpoint("stopped at tool-call limit")
                return

            name = call.function.name
            arguments = call.function.arguments

            print(f"\nJARVIS TOOL: {name}")
            print("Arguments:", clip(arguments, 1500))

            # Loop detection: identical call, nothing changed in between.
            try:
                key = (
                    name,
                    json.dumps(arguments, sort_keys=True, default=str),
                    change_counter,
                )
            except Exception:
                key = (name, str(arguments), change_counter)

            call_counts[key] = call_counts.get(key, 0) + 1
            repeats = call_counts[key]

            if repeats > MAX_REPEATED_CALLS + 2:
                print("\nJARVIS is stuck repeating the same call. Stopping.")
                checkpoint("stopped: repeated calls")
                return

            if repeats > MAX_REPEATED_CALLS:
                result = (
                    "Repeated call blocked: you already made this exact call "
                    "and nothing has changed since. Try a different approach: "
                    "re-read the relevant file, change the code, or change "
                    "the command."
                )
            else:
                result = execute_tool(name, arguments)

            result = clip(result)

            print("\nRESULT:")
            print(result)

            # Track file changes / verification.
            if name in FILE_CHANGE_TOOLS and not result.startswith("Tool error"):
                if "rejected" not in result.lower():
                    dirty = True
                    change_counter += 1
                    files_changed_this_step = True

            elif counts_as_verification(name, arguments if isinstance(arguments, dict) else {}):
                if command_succeeded(result):
                    dirty = False

            messages.append({
                "role": "tool",
                "tool_name": name,
                "content": result,
            })

        if files_changed_this_step:
            checkpoint(f"step {step}")

    print("\nJARVIS stopped: maximum reasoning steps reached.")
    print("Progress is saved in PLAN.md. Say 'continue' to resume.")
    checkpoint("stopped at step limit")


# ==========================================
# APPLICATION ENTRY POINT
# ==========================================

def main():

    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    init_git()

    print("=" * 45)
    print("              JARVIS AI")
    print("=" * 45)

    print(f"\nModel: {MODEL}")
    print(f"Project: {PROJECT_DIR}")
    print(f"Context window: {NUM_CTX}")
    print(f"Desktop control: {ENABLE_DESKTOP_CONTROL}")
    print(f"Automatic file changes: {AUTO_APPROVE_FILE_CHANGES}")
    print(f"Automatic commands: {AUTO_APPROVE_COMMANDS}")
    print(f"Git checkpoints: {bool(GIT)}")

    print("\nCommands:")
    print("/exit       - Exit JARVIS")
    print("/stop       - Create emergency stop signal (between tasks)")
    print("/resume     - Clear emergency stop signal")
    print("/newplan    - Discard the current PLAN.md")
    print("\nWhile a task is running:")
    print("  - Press Ctrl+C, or")
    print(f"  - Create the file {STOP_FILE.name} in the project folder "
          "from another terminal.")

    print("\nDescribe a task for JARVIS.\n")

    while True:

        try:
            instruction = input("\nYou: ").strip()

            if instruction.lower() in ("/exit", "exit"):
                break

            if instruction.lower() == "/stop":
                STOP_FILE.touch()
                print("Emergency stop signal created.")
                continue

            if instruction.lower() == "/resume":
                if STOP_FILE.exists():
                    STOP_FILE.unlink()
                print("Stop signal cleared.")
                continue

            if instruction.lower() == "/newplan":
                archive_plan()
                print("Plan archived to PLAN.old.md.")
                continue

            if not instruction:
                continue

            if STOP_FILE.exists():
                print("JARVIS is stopped. Type /resume to continue.")
                continue

            keep_awake()

            try:
                run_agent(instruction)

            finally:
                allow_sleep()

        except KeyboardInterrupt:
            allow_sleep()
            checkpoint("interrupted")
            print("\nJARVIS interrupted.")

        except Exception as error:
            allow_sleep()
            print(f"\nJARVIS ERROR: {type(error).__name__}: {error}")


if __name__ == "__main__":
    main()
    
