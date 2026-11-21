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
    pyautogui.FAILSAFE = True   # slam the mouse into a corner to abort
except Exception:
    pass


# ==========================================
# CONFIGURATION
# ==========================================

MODEL = "qwen3:8b"
KEEP_ALIVE = "10m"

NUM_CTX = 16384            # raise if your VRAM allows
NUM_PREDICT = 3000

MAX_STEPS = 30
MAX_TOOL_CALLS = 80
MAX_OUTPUT_CHARS = 8_000        # tool output the model sees
MAX_OBSERVATION_CHARS = 3_000   # screen-analysis JSON the model sees
MAX_HISTORY_CHARS = 36_000      # old tool output is squeezed past this
MAX_TIMEOUT = 120

MAX_REPEATED_CALLS = 3          # identical call, nothing changed in between
MAX_VERIFY_NAGS = 2             # times "done" is rejected without a passing run

DEBUG = False
AUTO_PLAN = True                # one thinking-enabled planning call per task

# Approval policy. Desktop actions ALWAYS require approval.
AUTO_APPROVE_FILE_CHANGES = True      # git checkpoints are the undo
AUTO_APPROVE_COMMANDS = False         # flip to True only inside a dedicated VM
CONFIRM_MEMORY_WRITES = True          # review every note and task write

# Real mouse/keyboard control must be enabled explicitly:
# PowerShell: $env:JARVIS_ENABLE_DESKTOP="1"
ENABLE_DESKTOP_CONTROL = os.getenv("JARVIS_ENABLE_DESKTOP", "0") == "1"

WORKSPACE_DIR = Path(workspace.WORKSPACE).resolve()
PLAN_FILE = WORKSPACE_DIR / "PLAN.md"
STOP_FILE = WORKSPACE_DIR / ".jarvis_stop"

ALLOWED_COMMANDS = {"python", "node", "npm", "npx", "git", "php"}


# ==========================================
# WINDOWS KEEP-AWAKE
# ==========================================

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002


def keep_awake():
    if os.name == "nt":
        ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
        )


def allow_sleep():
    if os.name == "nt":
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)


# ==========================================
# GENERAL HELPERS
# ==========================================

def clip(text, limit=MAX_OUTPUT_CHARS):
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
    return str(result).startswith((
        "Tool execution failed",
        "Action denied",
        "Invalid",
        "Bad arguments",
        "Error",
        "Desktop control is disabled",
        "Command not allowed",
    ))


# ==========================================
# GIT CHECKPOINTS (undo for everything)
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
    except Exception as error:
        print(f"WARNING: git setup failed: {error}")


def checkpoint(message):
    """Commit everything if anything changed. Never raises."""
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
    except Exception as error:
        print(f"(checkpoint failed: {error})")


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
    """Load saved state into the system prompt so the model never has to
    remember to ask for it."""
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
    except Exception as error:
        if DEBUG:
            print(f"[JARVIS DEBUG] Memory context unavailable: {error}")
        return ""


# ==========================================
# FILE EDITING
# ==========================================

def edit_file(filename, old, new):
    """Replace one exact snippet. Safer than rewriting a whole file."""
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

# Actions that change the real desktop: always need approval,
# and are followed by a screen observation.
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

# Everything that touches the real desktop at all (needs the enable flag).
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

def parse_arguments(tool_call):
    """Return (arguments_dict, error_message_or_None)."""
    name = tool_call.function.name
    arguments = tool_call.function.arguments or {}

    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError as error:
            return {}, f"Invalid JSON arguments for '{name}': {error}"

    if not isinstance(arguments, dict):
        return {}, f"Invalid arguments for '{name}': expected an object."

    return arguments, None


def validate_args(name, arguments):
    schema = SCHEMAS.get(name)

    if schema is None:
        return None

    missing = [k for k in schema["required"] if k not in arguments]
    unknown = [k for k in arguments if k not in schema["properties"]]

    if missing or unknown:
        allowed = list(schema["properties"])
        return (
            f"Bad arguments for {name}. Missing: {missing}. "
            f"Unknown: {unknown}. Allowed arguments: {allowed}."
        )

    return None


# ==========================================
# TOOL EXECUTION
# ==========================================

def execute_tool(name, arguments=None):
    """Run one tool.

    Accepts either execute_tool(name, arguments) or execute_tool(tool_call),
    where tool_call.function has name and arguments.
    """
    if not isinstance(name, str):
        tool_call = name
        name = tool_call.function.name
        arguments, arg_error = parse_arguments(tool_call)

        if arg_error:
            return arg_error
    elif arguments is None:
        arguments = {}

    function = AVAILABLE_FUNCTIONS.get(name)

    if function is None:
        return f"Error: This tool is not available: '{name}'."

    if name in DESKTOP_TOOLS and not ENABLE_DESKTOP_CONTROL:
        return (
            "Desktop control is disabled. Tell the user to set "
            "JARVIS_ENABLE_DESKTOP=1 and restart JARVIS. "
            "Use file and terminal tools instead."
        )

    problem = validate_args(name, arguments)

    if problem:
        return problem

    arguments = dict(arguments)

    # --- command safety -------------------------------------------------
    if name == "run_command":
        if arguments["command"] not in ALLOWED_COMMANDS:
            return (
                "Command not allowed. Allowed: "
                + ", ".join(sorted(ALLOWED_COMMANDS))
            )

        if not isinstance(arguments["args"], list) or not all(
            isinstance(a, str) for a in arguments["args"]
        ):
            return "Invalid arguments: 'args' must be a list of strings."

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
            return "Action denied by user."

    # --- reversibility --------------------------------------------------
    if name == "write_file":
        # Commit the previous state so any overwrite can be undone.
        checkpoint(f"before writing {arguments.get('filename')}")

    # --- run ------------------------------------------------------------
    try:
        print(f"\n[JARVIS TOOL] Executing {name}...")
        result = function(**arguments)
        print("[JARVIS TOOL] Result:", clip(result, 1500))
    except KeyboardInterrupt:
        raise
    except Exception as error:
        message = f"{type(error).__name__}: {error}"
        print("[JARVIS TOOL ERROR]", message)
        return f"Tool execution failed: {message}"

    # --- observe the screen after real desktop actions ------------------
    if name in DESKTOP_ACTIONS:
        try:
            observation = screen.analyze_screen()
            observation_text = clip(
                json.dumps(observation, ensure_ascii=False, default=str),
                MAX_OBSERVATION_CHARS,
            )
            return f"{result}{OBS_MARKER} {observation_text}"
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            print("[JARVIS OBSERVATION ERROR]", message)
            return (
                f"Action completed: {result}\n"
                f"Screen observation failed: {message}"
            )

    if isinstance(result, (dict, list)):
        return json.dumps(result, ensure_ascii=False, default=str)

    return str(result)


# ==========================================
# VERIFICATION AND SUCCESS DETECTION
# ==========================================

def command_succeeded(result):
    """
    Decide whether a run result means success.
    Adjust the key names to match what terminal.run_command and
    workspace.run_python_file actually return.
    """
    result = str(result)

    if is_error(result):
        return False

    try:
        data = json.loads(result)
    except ValueError:
        match = re.search(r"exit[ _-]?code\W+(-?\d+)", result, re.I)
        return bool(match) and match.group(1) == "0"

    if not isinstance(data, dict):
        return False

    if data.get("timed_out") or data.get("timeout"):
        return False

    for key in ("returncode", "return_code", "exit_code", "exitcode"):
        if key in data:
            return data[key] == 0

    for key in ("success", "ok"):
        if key in data:
            return bool(data[key])

    return False


def counts_as_verification(name, arguments):
    """Only runs that really exercise the code can clear the dirty flag."""
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

OBS_MARKER = "\nScreen after action:"


def message_size(message):
    if isinstance(message, dict):
        return len(str(message.get("content", "")))

    return len(str(getattr(message, "content", "") or "")) + len(
        str(getattr(message, "tool_calls", "") or "")
    )


def compact_history(messages, keep_recent=6):
    # 1. Only the newest screen observation is useful; drop the others.
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

    # 2. If still too long, squeeze old tool output.
    if sum(message_size(m) for m in messages) <= MAX_HISTORY_CHARS:
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

        if sum(message_size(m) for m in messages) <= MAX_HISTORY_CHARS:
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
        os.replace(PLAN_FILE, PLAN_FILE.with_name("PLAN.old.md"))


def generate_plan(instruction):
    """One thinking-enabled call that produces a short checklist."""
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

    except Exception as error:
        print(f"(planning skipped: {type(error).__name__}: {error})")
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

def ask_jarvis(user_input, max_steps=MAX_STEPS):
    # ---- plan handling ---------------------------------------------------
    plan_text = None

    if plan_has_open_items():
        print("\nAn unfinished plan exists in PLAN.md.")

        if approve("Resume the existing plan? (no = start fresh)",
                   "Resume? (y/n): "):
            plan_text = PLAN_FILE.read_text(encoding="utf-8", errors="replace")
        else:
            archive_plan()

    if plan_text is None and AUTO_PLAN:
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

    # ---- loop state ------------------------------------------------------
    total_calls = 0
    dirty = False            # files changed since the last passing run
    nags = 0
    change_counter = 0       # bumps whenever a project file changes
    call_counts = {}         # (name, args, change_counter) -> repeats

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
        except Exception as error:
            print(f"\n[JARVIS ERROR] {type(error).__name__}: {error}")
            print("Is Ollama running, and is the model pulled?")
            return None

        message = response.message
        messages.append(message)

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

        # ---- execute tool calls -----------------------------------------
        files_changed_this_step = False
        desktop_action_seen = False

        for call in tool_calls:

            check_stop()

            total_calls += 1

            if total_calls > MAX_TOOL_CALLS:
                print("\n[JARVIS] Maximum tool-call limit reached.")
                checkpoint("stopped at tool-call limit")
                return None

            name = call.function.name
            arguments, arg_error = parse_arguments(call)

            if arg_error:
                result = arg_error

            elif name in DESKTOP_ACTIONS and desktop_action_seen:
                result = (
                    "Action deferred: review the previous action's screen "
                    "observation before requesting another desktop action."
                )

            else:
                # Loop detection: identical call, nothing changed in between.
                key = (
                    name,
                    json.dumps(arguments, sort_keys=True, default=str),
                    change_counter,
                )
                call_counts[key] = call_counts.get(key, 0) + 1
                repeats = call_counts[key]

                if repeats > MAX_REPEATED_CALLS + 2:
                    print("\n[JARVIS] Stuck repeating the same call. Stopping.")
                    checkpoint("stopped: repeated calls")
                    return None

                if repeats > MAX_REPEATED_CALLS:
                    result = (
                        "Repeated call blocked: you already made this exact "
                        "call and nothing has changed since. Try a different "
                        "approach: re-read the file, change the code, or "
                        "change the command."
                    )
                else:
                    result = execute_tool(name, arguments)

                    if name in DESKTOP_ACTIONS and not is_error(result):
                        desktop_action_seen = True

            raw_result = str(result)

            # Track changes and verification using the UNCLIPPED result.
            if name in FILE_CHANGE_TOOLS and not is_error(raw_result):
                if arguments.get("filename") != "PLAN.md":
                    dirty = True
                    change_counter += 1
                    files_changed_this_step = True

            elif counts_as_verification(name, arguments):
                if command_succeeded(raw_result):
                    dirty = False

            messages.append({
                "role": "tool",
                "tool_name": name,
                "content": clip(raw_result),
            })

        if files_changed_this_step:
            checkpoint(f"step {step}")

    print("\n[JARVIS] Maximum tool-call steps reached.")
    print("Progress is saved in PLAN.md. Say 'continue' to resume.")
    checkpoint("stopped at step limit")
    return None


# ==========================================
# ENTRY POINT
# ==========================================

def main():
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    init_git()

    print("=" * 45)
    print("          JARVIS AI ASSISTANT")
    print("=" * 45)
    print("Model:", MODEL)
    print("Workspace:", workspace.WORKSPACE)
    print("Context window:", NUM_CTX)
    print("Desktop control:", ENABLE_DESKTOP_CONTROL)
    print("Automatic file changes:", AUTO_APPROVE_FILE_CHANGES)
    print("Automatic commands:", AUTO_APPROVE_COMMANDS)
    print("Git checkpoints:", bool(GIT))

    print("\nCommands:")
    print("/exit      - Close JARVIS")
    print("/stop      - Create emergency stop signal (between tasks)")
    print("/resume    - Clear emergency stop signal")
    print("/newplan   - Archive the current PLAN.md")
    print("\nDuring a task: press Ctrl+C, or create the file "
          f"{STOP_FILE.name} in the workspace from another terminal.")

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        command = user_input.lower()

        if not user_input:
            continue

        if command in {"exit", "quit", "/exit"}:
            break

        if command == "/stop":
            STOP_FILE.touch()
            print("Emergency stop signal created.")
            continue

        if command == "/resume":
            if STOP_FILE.exists():
                STOP_FILE.unlink()
            print("Stop signal cleared.")
            continue

        if command == "/newplan":
            archive_plan()
            print("Plan archived to PLAN.old.md.")
            continue

        if STOP_FILE.exists():
            print("JARVIS is stopped. Type /resume to continue.")
            continue

        keep_awake()

        try:
            ask_jarvis(user_input)

        except KeyboardInterrupt:
            print("\n[JARVIS] Interrupted.")
            checkpoint("interrupted")

        except Exception as error:
            print(f"\n[JARVIS ERROR] {type(error).__name__}: {error}")

        finally:
            allow_sleep()

    print("JARVIS stopped.")


if __name__ == "__main__":
    main()
