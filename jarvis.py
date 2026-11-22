import ctypes
import json
import os
import re
import shutil
import subprocess

from pathlib import Path

import ollama

from agent.memory import MemoryStore
from tools import computer, screen, terminal, workspace

try:
    import pyautogui
    pyautogui.FAILSAFE = True
except Exception:
    pass


# ==========================================
# CONFIGURATION
# ==========================================

MODEL = "qwen3:8b"
KEEP_ALIVE = "10m"

NUM_CTX = 16384
NUM_PREDICT = 3000

MAX_STEPS = 30
MAX_TOOL_CALLS = 80
MAX_OUTPUT_CHARS = 8_000
MAX_OBSERVATION_CHARS = 3_000
MAX_HISTORY_CHARS = 36_000
MAX_TIMEOUT = 120

MAX_REPEATED_CALLS = 3
MAX_REPEATED_HARD_STOP = 6          # FIX #1.5: separate soft block from hard stop
MAX_VERIFY_NAGS = 2

DEBUG = False
AUTO_PLAN = True

AUTO_APPROVE_FILE_CHANGES = True
AUTO_APPROVE_COMMANDS = False
CONFIRM_MEMORY_WRITES = True

ENABLE_DESKTOP_CONTROL = os.getenv("JARVIS_ENABLE_DESKTOP", "0") == "1"

WORKSPACE_DIR = Path(workspace.WORKSPACE).resolve()
PLAN_FILE = WORKSPACE_DIR / "PLAN.md"
STOP_FILE = WORKSPACE_DIR / ".jarvis_stop"

ALLOWED_COMMANDS = {"python", "node", "npm", "npx", "git", "php"}

# FIX #1.3: sentinel prefix so we never sniff content for errors.
ERROR_PREFIX = "Tool execution failed"

# FIX #1.7: UUID-ish marker unlikely to collide with tool output.
OBS_MARKER = "<<<JARVIS_SCREEN_OBS>>>"


# ==========================================
# WINDOWS KEEP-AWAKE
# ==========================================

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002


def keep_awake():
    if os.name == "nt":
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
            )
        except Exception:
            pass


def allow_sleep():
    if os.name == "nt":
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        except Exception:
            pass


# ==========================================
# GENERAL HELPERS
# ==========================================

def clip(text, limit=MAX_OUTPUT_CHARS):
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


def approve(message, prompt="Allow this action? (y/n): "):
    print("\n" + message)

    try:
        answer = input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("[JARVIS] Approval unavailable; action denied.")
        return False

    return answer in ("y", "yes")


def check_stop():
    if STOP_FILE.exists():
        raise KeyboardInterrupt("Emergency stop file detected.")


def is_error(result):
    # FIX #1.3: only the sentinel counts as an error.
    return isinstance(result, str) and result.startswith(ERROR_PREFIX)


def error(message):
    # FIX #1.3: helper that produces sentinel-prefixed errors.
    return f"{ERROR_PREFIX}: {message}"


# ==========================================
# GIT CHECKPOINTS
# ==========================================

GIT = shutil.which("git")


def _git(*args, timeout=30):
    return subprocess.run(
        [GIT, *args],
        cwd=WORKSPACE_DIR,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def init_git():
    if not GIT:
        print("WARNING: git not found. No checkpoints will be created.")
        return

    try:
        if not (WORKSPACE_DIR / ".git").exists():
            _git("init")

        gitignore = WORKSPACE_DIR / ".gitignore"

        if not gitignore.exists():
            gitignore.write_text(
                "node_modules/\n.venv/\nvenv/\n__pycache__/\n"
                ".agent_backups/\n.jarvis_stop\n*.tmp\n",
                encoding="utf-8",
            )
    except Exception as exc:
        print(f"WARNING: git setup failed: {exc}")


def checkpoint(message):
    if not GIT:
        return

    try:
        _git("add", "-A")

        if not _git("status", "--porcelain").stdout.strip():
            return

        _git(
            "-c", "user.name=JARVIS",
            "-c", "user.email=jarvis@localhost",
            "commit", "-m", f"jarvis: {message}",
        )
    except Exception as exc:
        print(f"(checkpoint failed: {exc})")


# ==========================================
# MEMORY AND TASK TOOLS
# ==========================================

def save_memory(kind, content, project=None):
    with MemoryStore() as memory:
        memory_id = memory.save_memory(kind, content, project)
    return {"saved": True, "id": memory_id}


def list_memories(kind=None, project=None, limit=20):
    with MemoryStore() as memory:
        return memory.list_memories(kind, project, limit)


def create_task(title, details="", project=None):
    with MemoryStore() as memory:
        task_id = memory.create_task(title, details, project)
    return {"created": True, "id": task_id, "status": "planned"}


def update_task_status(task_id, status):
    with MemoryStore() as memory:
        memory.update_task_status(task_id, status)
    return {"updated": True, "id": task_id, "status": status}


def list_tasks(outstanding_only=False, limit=20):
    with MemoryStore() as memory:
        return memory.list_tasks(outstanding_only, limit)


def build_memory_context():
    try:
        with MemoryStore() as memory:
            tasks = memory.list_tasks(True, 10)
            notes = memory.list_memories(None, None, 10)

        return (
            "\nOUTSTANDING TASKS (from persistent history):\n"
            + clip(json.dumps(tasks, ensure_ascii=False, default=str), 2000)
            + "\n\nSAVED NOTES AND DECISIONS:\n"
            + clip(json.dumps(notes, ensure_ascii=False, default=str), 2000)
            + "\n"
        )
    except Exception as exc:
        if DEBUG:
            print(f"[JARVIS DEBUG] Memory context unavailable: {exc}")
        return ""


# ==========================================
# FILE EDITING
# ==========================================

def edit_file(filename, old, new):
    if not isinstance(old, str) or not old:
        raise ValueError("'old' must be a non-empty string.")

    if not isinstance(new, str):
        raise ValueError("'new' must be a string.")

    text = workspace.read_file(filename)

    if isinstance(text, dict) and "content" in text:
        text = text["content"]

    if not isinstance(text, str):
        text = str(text)

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

    workspace.write_file(filename, text.replace(old, new))

    return f"Edited {filename}."


# ==========================================
# TOOL REGISTRY
# ==========================================

AVAILABLE_FUNCTIONS = {
    "open_notepad": computer.open_notepad,
    "type_text": computer.type_text,
    "press_key": computer.press_key,
    "press_hotkey": computer.press_hotkey,
    "select_all_and_replace_text": computer.select_all_and_replace_text,
    "move_mouse": computer.move_mouse,
    "click_mouse": computer.click_mouse,
    "right_click_mouse": computer.right_click_mouse,
    "double_click_mouse": computer.double_click_mouse,
    "scroll_mouse": computer.scroll_mouse,
    "drag_mouse": computer.drag_mouse,
    "get_screen_size": computer.get_screen_size,
    "take_screenshot": computer.take_screenshot,
    "analyze_screen": screen.analyze_screen,
    "list_files": workspace.list_files,
    "read_file": workspace.read_file,
    "write_file": workspace.write_file,
    "edit_file": edit_file,
    "run_python_file": workspace.run_python_file,
    "run_command": terminal.run_command,
    "save_memory": save_memory,
    "list_memories": list_memories,
    "create_task": create_task,
    "update_task_status": update_task_status,
    "list_tasks": list_tasks,
}

DESKTOP_ACTIONS = {
    "open_notepad",
    "type_text",
    "press_key",
    "press_hotkey",
    "select_all_and_replace_text",
    "click_mouse",
    "right_click_mouse",
    "double_click_mouse",
    "scroll_mouse",
    "drag_mouse",
}

DESKTOP_TOOLS = DESKTOP_ACTIONS | {
    "move_mouse",
    "get_screen_size",
    "take_screenshot",
    "analyze_screen",
}

COMMAND_TOOLS = {"run_command", "run_python_file"}
FILE_CHANGE_TOOLS = {"write_file", "edit_file"}
MEMORY_WRITE_TOOLS = {"save_memory", "create_task", "update_task_status"}


def needs_confirmation(name):
    if name in DESKTOP_ACTIONS:
        return True

    if name in COMMAND_TOOLS:
        return not AUTO_APPROVE_COMMANDS

    if name in FILE_CHANGE_TOOLS:
        return not AUTO_APPROVE_FILE_CHANGES

    if name in MEMORY_WRITE_TOOLS:
        return CONFIRM_MEMORY_WRITES

    return False


def tool_schema(name, description, properties=None, required=None):
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
    tool_schema("open_notepad", "Open Windows Notepad."),
    tool_schema(
        "type_text",
        "Type text into the currently focused application.",
        {"text": {"type": "string"}},
        ["text"],
    ),
    tool_schema(
        "press_key",
        "Press a keyboard key such as enter, tab or esc.",
        {"key": {"type": "string"}},
        ["key"],
    ),
    tool_schema(
        "press_hotkey",
        "Press a keyboard shortcut such as Ctrl+S or Alt+Tab. Requires approval.",
        {"keys": {"type": "array", "items": {"type": "string"}}},
        ["keys"],
    ),
    tool_schema(
        "select_all_and_replace_text",
        "Select all text in the focused control and replace it. "
        "This may overwrite the current document and requires approval.",
        {"text": {"type": "string"}},
        ["text"],
    ),
    tool_schema(
        "move_mouse",
        "Move the mouse to screen coordinates.",
        {
            "x": {"type": "integer"},
            "y": {"type": "integer"},
            "duration": {"type": "number"},
        },
        ["x", "y"],
    ),
    tool_schema(
        "right_click_mouse",
        "Right-click at screen coordinates.",
        {"x": {"type": "integer"}, "y": {"type": "integer"}},
        ["x", "y"],
    ),
    tool_schema(
        "double_click_mouse",
        "Double-click at screen coordinates.",
        {"x": {"type": "integer"}, "y": {"type": "integer"}},
        ["x", "y"],
    ),
    tool_schema(
        "scroll_mouse",
        "Scroll vertically at a location; positive clicks scroll up "
        "and negative clicks scroll down.",
        {
            "clicks": {"type": "integer"},
            "x": {"type": "integer"},
            "y": {"type": "integer"},
        },
        ["clicks"],
    ),
    tool_schema(
        "drag_mouse",
        "Drag the left mouse button between two screen points.",
        {
            "start_x": {"type": "integer"},
            "start_y": {"type": "integer"},
            "end_x": {"type": "integer"},
            "end_y": {"type": "integer"},
            "duration": {"type": "number"},
        },
        ["start_x", "start_y", "end_x", "end_y"],
    ),
    tool_schema(
        "click_mouse",
        "Click at screen coordinates.",
        {"x": {"type": "integer"}, "y": {"type": "integer"}},
        ["x", "y"],
    ),
    tool_schema("get_screen_size", "Get screen dimensions."),
    tool_schema("take_screenshot", "Capture a screenshot of the desktop."),
    tool_schema(
        "analyze_screen",
        "Analyze a fresh desktop screenshot with the local vision model and "
        "return visible elements with pixel coordinates. This tool only "
        "observes; it does not click or type.",
    ),
    tool_schema("list_files", "List files in the JARVIS workspace."),
    tool_schema(
        "read_file",
        "Read a text file inside the JARVIS workspace.",
        {"filename": {"type": "string"}},
        ["filename"],
    ),
    tool_schema(
        "write_file",
        "Create a NEW workspace file, or fully rewrite a small one. "
        "For changes to existing files prefer edit_file. For large new "
        "files, write a short skeleton and extend it with edit_file.",
        {"filename": {"type": "string"}, "content": {"type": "string"}},
        ["filename", "content"],
    ),
    tool_schema(
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
    tool_schema(
        "run_python_file",
        "Execute a Python file inside the workspace and return its output.",
        {"filename": {"type": "string"}},
        ["filename"],
    ),
    tool_schema(
        "run_command",
        "Run one approved Python, Node, npm, npx, Git, or PHP command "
        "without a shell. The working directory must be inside the JARVIS "
        "workspace. Use this to run tests.",
        {
            "command": {
                "type": "string",
                "enum": ["python", "node", "npm", "npx", "git", "php"],
            },
            "args": {"type": "array", "items": {"type": "string"}},
            "cwd": {"type": "string"},
            "timeout": {"type": "number"},
        },
        ["command", "args"],
    ),
    tool_schema(
        "save_memory",
        "Save a durable project note or preference. Never save secrets "
        "or full conversation transcripts.",
        {
            "kind": {
                "type": "string",
                "enum": ["project_structure", "decision", "preference", "note"],
            },
            "content": {"type": "string"},
            "project": {"type": "string"},
        },
        ["kind", "content"],
    ),
    tool_schema(
        "list_memories",
        "Search recent saved notes, decisions, project structures, "
        "and preferences.",
        {
            "kind": {
                "type": "string",
                "enum": ["project_structure", "decision", "preference", "note"],
            },
            "project": {"type": "string"},
            "limit": {"type": "integer"},
        },
    ),
    tool_schema(
        "create_task",
        "Add a task to persistent JARVIS task history.",
        {
            "title": {"type": "string"},
            "details": {"type": "string"},
            "project": {"type": "string"},
        },
        ["title"],
    ),
    tool_schema(
        "update_task_status",
        "Change a saved task status.",
        {
            "task_id": {"type": "integer"},
            "status": {
                "type": "string",
                "enum": ["planned", "in_progress", "completed", "blocked"],
            },
        },
        ["task_id", "status"],
    ),
    tool_schema(
        "list_tasks",
        "List saved tasks, optionally excluding completed tasks.",
        {
            "outstanding_only": {"type": "boolean"},
            "limit": {"type": "integer"},
        },
    ),
]

SCHEMAS = {t["function"]["name"]: t["function"]["parameters"] for t in TOOLS}


# ==========================================
# ARGUMENT PARSING AND VALIDATION
# ==========================================

# FIX #1.8: enforce types declared in schema.
_TYPES = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def parse_arguments(tool_call):
    """Return (arguments_dict, error_message_or_None)."""
    name = tool_call.function.name
    arguments = tool_call.function.arguments or {}

    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError as exc:
            return {}, error(f"Invalid JSON arguments for '{name}': {exc}")

    if not isinstance(arguments, dict):
        return {}, error(
            f"Invalid arguments for '{name}': expected an object, "
            f"got {type(arguments).__name__}."
        )

    return arguments, None


def validate_args(name, arguments):
    schema = SCHEMAS.get(name)

    if schema is None:
        return None

    required = schema.get("required", [])
    properties = schema.get("properties", {})

    missing = [k for k in required if k not in arguments]
    unknown = [k for k in arguments if k not in properties]

    if missing or unknown:
        allowed = list(properties)
        return (
            f"Bad arguments for {name}. Missing: {missing}. "
            f"Unknown: {unknown}. Allowed arguments: {allowed}."
        )

    for key, value in arguments.items():
        declared = properties[key].get("type")
        expected = _TYPES.get(declared)

        if expected is None:
            continue

        # bool is a subclass of int; special-case it.
        if declared == "integer" and isinstance(value, bool):
            return f"Bad arguments for {name}: '{key}' must be integer, got boolean."

        if not isinstance(value, expected):
            return (
                f"Bad arguments for {name}: '{key}' must be "
                f"{declared}, got {type(value).__name__}."
            )

    return None


def _in_workspace(path_value):
    """Resolve a workspace-relative (or absolute) path and confirm it stays
    inside WORKSPACE_DIR. Returns the resolved string, or raises ValueError."""
    candidate = Path(path_value)

    if not candidate.is_absolute():
        candidate = WORKSPACE_DIR / candidate

    resolved = candidate.resolve()

    try:
        resolved.relative_to(WORKSPACE_DIR)
    except ValueError:
        raise ValueError(
            f"Path '{path_value}' is outside the workspace."
        )

    return str(resolved)


# ==========================================
# TOOL EXECUTION
# ==========================================

def execute_tool(name, arguments=None):
    """Execute one tool by name. Also accepts a single ToolCall object."""
    if not isinstance(name, str):
        tool_call = name
        name = tool_call.function.name
        arguments, arg_error = parse_arguments(tool_call)

        if arg_error:
            return arg_error
    elif arguments is None:
        arguments = {}

    if not isinstance(arguments, dict):
        return error(f"Invalid arguments for '{name}'.")

    function = AVAILABLE_FUNCTIONS.get(name)

    if function is None:
        return error(f"This tool is not available: '{name}'.")

    if name in DESKTOP_TOOLS and not ENABLE_DESKTOP_CONTROL:
        return error(
            "Desktop control is disabled. Tell the user to set "
            "JARVIS_ENABLE_DESKTOP=1 and restart JARVIS. "
            "Use file and terminal tools instead."
        )

    problem = validate_args(name, arguments)

    if problem:
        return error(problem)

    arguments = dict(arguments)

    # --- command safety -------------------------------------------------
    if name == "run_command":
        if arguments.get("command") not in ALLOWED_COMMANDS:
            return error(
                "Command not allowed. Allowed: "
                + ", ".join(sorted(ALLOWED_COMMANDS))
            )

        if not isinstance(arguments.get("args"), list) or not all(
            isinstance(a, str) for a in arguments["args"]
        ):
            return error("Invalid arguments: 'args' must be a list of strings.")

        # FIX #2.8: sandbox cwd.
        if "cwd" in arguments and arguments["cwd"]:
            try:
                arguments["cwd"] = _in_workspace(arguments["cwd"])
            except (ValueError, OSError) as exc:
                return error(f"Invalid 'cwd': {exc}")

        if "timeout" in arguments:
            try:
                arguments["timeout"] = max(
                    1, min(float(arguments["timeout"]), MAX_TIMEOUT)
                )
            except (TypeError, ValueError):
                arguments.pop("timeout")

    # --- approval -------------------------------------------------------
    if needs_confirmation(name):
        print(f"\nJARVIS wants to execute: {name}")
        print("Arguments:", clip(arguments, 1500))

        if not approve(""):
            return error(
                "Action denied by user. Do not retry this action; "
                "ask the user how to proceed instead."
            )

    # --- reversibility --------------------------------------------------
    if name == "write_file":
        checkpoint(f"before writing {arguments.get('filename')}")

    # --- run ------------------------------------------------------------
    try:
        print(f"\n[JARVIS TOOL] Executing {name}...")
        result = function(**arguments)
        print("[JARVIS TOOL] Result:", clip(result, 1500))
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        print("[JARVIS TOOL ERROR]", message)
        return error(message)

    # --- observe the screen after real desktop actions ------------------
    if name in DESKTOP_ACTIONS:
        try:
            observation = screen.analyze_screen()
            observation_text = clip(
                json.dumps(observation, ensure_ascii=False, default=str),
                MAX_OBSERVATION_CHARS,
            )
            return f"{result}{OBS_MARKER} {observation_text}"
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            print("[JARVIS OBSERVATION ERROR]", message)
            return (
                f"{result}\n"
                f"Screen observation failed: {message}"
            )

    if isinstance(result, (dict, list)):
        return json.dumps(result, ensure_ascii=False, default=str)

    return str(result)


# ==========================================
# VERIFICATION AND SUCCESS DETECTION
# ==========================================

def command_succeeded(result):
    """Decide whether a run result means success.

    Preferred: run_command/run_python_file return a JSON-serializable dict
    with one of {returncode, return_code, exit_code, exitcode} or
    {success, ok}, plus optionally timed_out/timeout.
    """
    text = str(result)

    if is_error(text):
        return False

    data = None
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        data = None

    if isinstance(data, dict):
        if data.get("timed_out") or data.get("timeout"):
            return False

        for key in ("returncode", "return_code", "exit_code", "exitcode"):
            if key in data:
                return data[key] == 0

        for key in ("success", "ok"):
            if key in data:
                return bool(data[key])

        return False

    # Fallback for plain-text results: look for an exit code line.
    match = re.search(r"exit[ _-]?code\W+(-?\d+)", text, re.I)
    if match:
        return match.group(1) == "0"

    return False


def counts_as_verification(name, arguments):
    if name == "run_python_file":
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
# CONTEXT MANAGEMENT
# ==========================================

def message_size(message):
    if isinstance(message, dict):
        return len(str(message.get("content", "")))

    return len(str(getattr(message, "content", "") or "")) + len(
        str(getattr(message, "tool_calls", "") or "")
    )


def compact_history(messages, keep_recent=6):
    # 1. Only the newest screen observation is kept.
    observation_indexes = [
        i for i, m in enumerate(messages)
        if isinstance(m, dict)
        and m.get("role") == "tool"
        and OBS_MARKER in str(m.get("content", ""))
    ]

    for i in observation_indexes[:-1]:
        content = messages[i]["content"]
        messages[i]["content"] = (
            content.split(OBS_MARKER)[0] + "\n[old screen observation removed]"
        )

    # FIX #1.6: O(n) instead of O(n^2). Compute sizes once.
    sizes = [message_size(m) for m in messages]
    total = sum(sizes)

    if total <= MAX_HISTORY_CHARS:
        return

    cutoff = len(messages) - keep_recent

    for index, message in enumerate(messages):
        if total <= MAX_HISTORY_CHARS:
            break

        if index < 2 or index >= cutoff:
            continue

        if isinstance(message, dict) and message.get("role") == "tool":
            old = str(message.get("content", ""))

            if len(old) > 600:
                new = (
                    old[:250]
                    + "\n...[old output removed to save context]...\n"
                    + old[-250:]
                )
                total -= len(old) - len(new)
                message["content"] = new


# ==========================================
# PLAN FILE
# ==========================================

# FIX #1.13: cheap heuristic so trivial requests skip planning.
_PLAN_TRIGGERS = (
    "write", "build", "implement", "create", "refactor", "fix", "add",
    "make", "update", "delete", "remove", "test", "migrate", "install",
    "debug", "rename", "convert", "generate", "script", "project",
)


def looks_like_a_task(instruction):
    low = instruction.lower().strip()
    if len(low) > 40:
        return True
    return any(trigger in low for trigger in _PLAN_TRIGGERS)


def plan_has_open_items():
    if not PLAN_FILE.exists():
        return False

    return "[ ]" in PLAN_FILE.read_text(encoding="utf-8", errors="replace")


def archive_plan():
    if PLAN_FILE.exists():
        os.replace(PLAN_FILE, PLAN_FILE.with_name("PLAN.old.md"))


def generate_plan(instruction):
    print("\nJARVIS is planning...")

    try:
        response = ollama.chat(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior software engineer. If the task is "
                        "a simple question or a single quick action, reply "
                        "with exactly NO_PLAN. Otherwise produce a markdown "
                        "checklist of 4-12 small, concrete, verifiable "
                        "steps, one per line, formatted '- [ ] step'. The "
                        "final steps must be running tests/the app and "
                        "fixing failures. Output ONLY the checklist."
                    ),
                },
                {"role": "user", "content": instruction},
            ],
            think=True,
            keep_alive=KEEP_ALIVE,
            options={
                "temperature": 0.3,
                "num_ctx": NUM_CTX,
                "num_predict": 1500,
            },
        )

        text = (response.message.content or "").strip()

        if "NO_PLAN" in text or "[ ]" not in text:
            return None

        PLAN_FILE.write_text(
            f"# Task\n{instruction}\n\n# Plan\n{text}\n",
            encoding="utf-8",
        )

        print(text)
        return text

    except Exception as exc:
        print(f"(planning skipped: {type(exc).__name__}: {exc})")
        return None


# ==========================================
# SYSTEM PROMPT
# ==========================================

SYSTEM_PROMPT = """
You are JARVIS, a local Windows coding and computer assistant.

You can inspect, read, create, and edit files in your configured workspace;
run Python files and approved developer commands there; use the registered
computer-control tools; and use persistent local memory and task tracking.
You can analyze screenshots with a local vision model.

WORKFLOW:
1. If PLAN.md exists, follow it. Work on ONE unchecked item at a time.
2. Inspect relevant files before modifying them.
3. Implement in small pieces, then run the code or tests to verify.
4. If something fails, read the error, fix the cause, and run again.
   Never repeat an identical failing call; try a different approach.
5. When an item is verified, mark it done by changing '[ ]' to '[x]'
   in PLAN.md using edit_file.
6. When everything is verified, report what you did, how you verified it,
   and what remains.

RULES:
1. Use tools to perform requested actions. Do not merely describe them.
2. Never claim an action succeeded unless its tool returned successfully.
   Never claim code works unless you ran it and it passed.
3. Prefer edit_file for changes to existing files. Keep files reasonably
   small; for big files, write a skeleton then extend it with edit_file.
4. Make focused changes and do not modify unrelated projects.
5. Work only with files inside the configured workspace.
6. Ask for approval when a tool requires it; never bypass approval.
   If an action is denied, do not retry it.
7. Check saved notes and outstanding tasks when relevant. Save only durable
   project decisions, structures and preferences. Never save credentials,
   secrets, or full transcripts.
8. Prefer file and terminal tools over mouse and keyboard. Use the desktop
   only when a task truly needs a GUI.
9. Use screen analysis to locate visible controls. Treat coordinates as
   suggestions. Never interact with password fields, payment screens, or
   account-security settings. Do not send messages, submit forms, purchase
   items, or delete user data without explicit authorization.
10. Request at most one desktop action per response, then use its screen
    observation before deciding the next desktop action.
11. Run developer commands only through run_command or run_python_file.
    Do not install software without user authorization.
12. Use real structured tool calls. Never invent tool results.
13. If you cannot safely continue, stop and explain why.
"""


# ==========================================
# AGENT LOOP
# ==========================================

def _assistant_dict(message):
    """Normalize the assistant message into a dict so it survives any
    future compaction or serialization round-trips safely."""
    return {
        "role": "assistant",
        "content": message.content or "",
        "tool_calls": message.tool_calls or [],
    }


def ask_jarvis(user_input, max_steps=MAX_STEPS):
    plan_text = None

    if plan_has_open_items():
        print("\nAn unfinished plan exists in PLAN.md.")

        if approve("Resume the existing plan? (no = start fresh)",
                   "Resume? (y/n): "):
            plan_text = PLAN_FILE.read_text(encoding="utf-8", errors="replace")
        else:
            archive_plan()

    if plan_text is None and AUTO_PLAN and looks_like_a_task(user_input):
        plan_text = generate_plan(user_input)

    system_content = SYSTEM_PROMPT + build_memory_context()

    if plan_text:
        system_content += (
            "\nCURRENT PLAN (also stored in PLAN.md; keep it updated):\n"
            + plan_text
        )

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_input},
    ]

    total_calls = 0
    dirty = False
    nags = 0
    change_counter = 0
    call_counts = {}

    for step in range(1, max_steps + 1):

        check_stop()

        print("\n" + "=" * 45)
        print(f"JARVIS STEP {step}/{max_steps}")
        print("=" * 45)

        compact_history(messages)

        try:
            response = ollama.chat(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                think=False,
                keep_alive=KEEP_ALIVE,
                options={
                    "temperature": 0,
                    "num_ctx": NUM_CTX,
                    "num_predict": NUM_PREDICT,
                },
            )
        except Exception as exc:
            print(f"\n[JARVIS ERROR] {type(exc).__name__}: {exc}")
            print(
                "Common causes: Ollama server not running, model not pulled, "
                "or not enough VRAM for num_ctx. Try: ollama list, ollama ps"
            )
            return None

        message = response.message
        messages.append(_assistant_dict(message))

        if DEBUG:
            print(f"[JARVIS DEBUG] Tool calls: {message.tool_calls}")

        tool_calls = message.tool_calls or []

        # ---- the model believes it is finished --------------------------
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

            final = message.content or "No final response was provided."
            print(f"\n[JARVIS] {final}")

            if dirty:
                print("\nNOTE: files changed after the last passing run; "
                      "the result may be unverified.")

            checkpoint("final state")
            return final

        # ---- execute tool
