import json

import ollama

from agent.memory import MemoryStore
from tools import computer, screen, terminal, workspace

MODEL = "qwen3:8b"
MAX_STEPS = 10


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

CONFIRMATION_REQUIRED = {
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
    "write_file",
    "run_python_file",
    "run_command",
    "save_memory",
    "create_task",
    "update_task_status",
}


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
        "Select all text in the focused control and replace it. This may overwrite the current document and requires approval.",
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
        "Scroll vertically at a location; positive clicks scroll up and negative clicks scroll down.",
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
        {
            "x": {"type": "integer"},
            "y": {"type": "integer"},
        },
        ["x", "y"],
    ),
    tool_schema("get_screen_size", "Get screen dimensions."),
    tool_schema("take_screenshot", "Capture a screenshot of the desktop."),
    tool_schema(
        "analyze_screen",
        "Analyze a fresh desktop screenshot with the local vision model and return visible elements with pixel coordinates. This tool only observes; it does not click or type.",
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
        "Create or update a workspace file, backing up existing content.",
        {
            "filename": {"type": "string"},
            "content": {"type": "string"},
        },
        ["filename", "content"],
    ),
    tool_schema(
        "run_python_file",
        "Execute a Python file inside the workspace and return its output.",
        {"filename": {"type": "string"}},
        ["filename"],
    ),
    tool_schema(
        "run_command",
        "Run one approved Python, Node, npm, npx, Git, or PHP command without a shell. The working directory must be inside the JARVIS workspace; every command requires user approval.",
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
        "Save a durable project note or preference after user approval. Never save secrets or full conversation transcripts.",
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
        "Search recent saved notes, decisions, project structures, and preferences.",
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
        "Add a task to persistent JARVIS task history after user approval.",
        {
            "title": {"type": "string"},
            "details": {"type": "string"},
            "project": {"type": "string"},
        },
        ["title"],
    ),
    tool_schema(
        "update_task_status",
        "Change a saved task status after user approval.",
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


def execute_tool(tool_call):
    name = tool_call.function.name
    arguments = tool_call.function.arguments or {}

    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError as error:
            return f"Invalid JSON arguments for '{name}': {error}"

    if not isinstance(arguments, dict):
        return f"Invalid arguments for '{name}': expected an object."

    function = AVAILABLE_FUNCTIONS.get(name)
    if function is None:
        return f"Error: This tool is not available: '{name}'."

    if name in CONFIRMATION_REQUIRED:
        print(f"\nJARVIS wants to execute: {name}")
        print("Arguments:", arguments)

        try:
            approval = input("Allow this action? (y/n): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("[JARVIS] Approval unavailable; action denied.")
            return "Action denied by user."

        if approval != "y":
            return "Action denied by user."

    try:
        print(f"\n[JARVIS TOOL] Executing {name}...")
        result = function(**arguments)
        print("[JARVIS TOOL] Result:", result)
    except Exception as error:
        error_message = f"{type(error).__name__}: {error}"
        print("[JARVIS TOOL ERROR]", error_message)
        return f"Tool execution failed: {error_message}"

    if name in DESKTOP_ACTIONS:
        try:
            observation = screen.analyze_screen()
            return (
                f"{result}\nScreen after action: "
                f"{json.dumps(observation, ensure_ascii=False)}"
            )
        except Exception as error:
            observation_error = f"{type(error).__name__}: {error}"
            print("[JARVIS OBSERVATION ERROR]", observation_error)
            return (
                f"Action completed: {result}\n"
                f"Screen observation failed: {observation_error}"
            )

    if isinstance(result, (dict, list)):
        return json.dumps(result, ensure_ascii=False)
    return str(result)

def ask_jarvis(user_input, max_steps=MAX_STEPS):
    messages = [
        {
            "role": "system",
            "content": """
You are JARVIS, a local Windows coding and computer assistant.

You can inspect, read, create, and update files in your configured workspace;
run Python files there; use the registered computer-control tools; and use
persistent local memory and task tracking. You can analyze screenshots with a
local vision model.

Rules:
1. Use tools to perform requested actions. Do not merely describe them.
2. Never claim an action succeeded unless its tool returned successfully.
3. Inspect relevant files before modifying them.
4. Make focused changes and do not modify unrelated projects.
5. Ask for approval when a tool requires it; never bypass approval.
6. Work only with files inside the configured workspace.
7. If a tool fails, inspect the result and explain the error.
8. Report what you accomplished when finished.
9. Check saved memories and outstanding tasks when they are relevant.
10. Save only durable project decisions, structures, preferences, and meaningful
    requested task progress. Never save credentials, secrets, or full transcripts.
11. Memory and task changes require user approval; do not retry if denied.
12. Use screen analysis to locate visible controls when coordinates are uncertain.
    Treat reported coordinates as suggestions and never bypass click approval.
13. Screen images are sent only to the configured local Ollama vision model.
14. Request at most one desktop action per response, then use its screen
    observation before deciding the next desktop action.
15. Run developer commands only through run_command. It uses a fixed executable
    allowlist, no shell, a workspace working directory, a timeout, and requires
    approval. Never attempt to bypass its restrictions.
""",
        },
        {"role": "user", "content": user_input},
    ]

    for step in range(max_steps):
        try:
            response = ollama.chat(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                think=True,
            )
        except Exception as error:
            print(f"\n[JARVIS ERROR] {type(error).__name__}: {error}")
            return None

        message = response.message
        print(f"\n[JARVIS DEBUG] Step: {step + 1}")
        print(f"[JARVIS DEBUG] Tool calls: {message.tool_calls}")

        if message.tool_calls:
            messages.append(message)

            desktop_action_seen = False
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                if tool_name in DESKTOP_ACTIONS and desktop_action_seen:
                    result = (
                        "Action deferred: review the previous action's screen "
                        "observation before requesting another desktop action."
                    )
                else:
                    result = execute_tool(tool_call)
                    if tool_name in DESKTOP_ACTIONS:
                        desktop_action_seen = True
                messages.append(
                    {
                        "role": "tool",
                        "tool_name": tool_name,
                        "content": str(result),
                    }
                )

            continue

        if message.content:
            print(f"\n[JARVIS] {message.content}")
            return message.content

        print("\n[JARVIS] No response received.")
        return None

    print("\n[JARVIS] Maximum tool-call steps reached.")
    return None


def main():
    print("=" * 45)
    print("          JARVIS AI ASSISTANT")
    print("=" * 45)
    print("Model:", MODEL)
    print("Workspace:", workspace.WORKSPACE)
    print("Type 'exit' to close JARVIS.")

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue

        if user_input.lower() in {"exit", "quit"}:
            break

        ask_jarvis(user_input)

    print("JARVIS stopped.")


if __name__ == "__main__":
    main()
