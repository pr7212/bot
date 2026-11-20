import ollama

from tools import computer

MODEL = "qwen3:8b"

AVAILABLE_FUNCTIONS = {
    "open_notepad": computer.open_notepad,
    "type_text": computer.type_text,
    "press_key": computer.press_key,
    "move_mouse": computer.move_mouse,
    "click_mouse": computer.click_mouse,
    "get_screen_size": computer.get_screen_size,
    "take_screenshot": computer.take_screenshot,
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "open_notepad",
            "description": "Launch Windows Notepad.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "type_text",
            "description": "Type text on the keyboard.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "press_key",
            "description": "Press a keyboard key such as enter, tab or esc.",
            "parameters": {
                "type": "object",
                "properties": {"key": {"type": "string"}},
                "required": ["key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_mouse",
            "description": "Move the mouse to screen coordinates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "duration": {"type": "number"},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click_mouse",
            "description": "Click the mouse at screen coordinates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_screen_size",
            "description": "Get screen width and height.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "take_screenshot",
            "description": "Take a screenshot of the desktop.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


def execute_tool(tool_call):
    name = tool_call.function.name
    arguments = dict(tool_call.function.arguments or {})
    function = AVAILABLE_FUNCTIONS.get(name)
    if function is None:
        return f"Error: Unknown tool '{name}'."

    try:
        if name in {"move_mouse", "click_mouse"}:
            arguments["x"] = int(arguments["x"])
            arguments["y"] = int(arguments["y"])

        if name == "move_mouse" and "duration" in arguments:
            arguments["duration"] = float(arguments["duration"])

        print(f"\n[JARVIS TOOL] Executing: {name}")
        print(f"[JARVIS TOOL] Arguments: {arguments}")

        result = function(**arguments)
        print(f"[JARVIS TOOL] Result: {result}")
        return str(result)
    except Exception as error:
        print(f"[JARVIS ERROR] {error}")
        return f"Tool execution failed: {error}"


def ask_jarvis(user_input, max_steps=6):
    messages = [
        {
            "role": "system",
            "content": """
You are JARVIS, a Windows computer assistant.

You have access to real computer-control tools.

Rules:
1. Use tools to perform actions requested by the user.
2. Never describe a tool call as completed without executing it.
3. For opening Notepad and typing:
   - Call open_notepad first.
   - Wait for its result.
   - Then call type_text.
4. Use click_mouse for mouse clicks.
5. Use move_mouse for mouse movement.
6. When a tool fails, explain the error.
7. Never invent successful execution.
8. Do not perform unrelated actions.
""",
        },
        {
            "role": "user",
            "content": user_input
        },
    ]

    for step in range(max_steps):
        response = ollama.chat(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            think=True
        )
        message = response.message

        print(f"\n[JARVIS DEBUG] Step: {step + 1}")
        print(f"[JARVIS DEBUG] Tool calls: {message.tool_calls}")

        if message.tool_calls:
            messages.append(message)
            for tool_call in message.tool_calls:
                result = execute_tool(tool_call)
                messages.append({
                    "role": "tool",
                    "tool_name": tool_call.function.name,
                    "content": str(result)
                })
            continue

        if message.content:
            print(f"\n[JARVIS] {message.content}")
            return message.content

        print("\n[JARVIS] No response received.")
        return None

    print("\n[JARVIS] Maximum execution steps reached.")
    return None


def main():
    print("=" * 45)
    print("          JARVIS AI ASSISTANT")
    print("=" * 45)
    print(f"Model: {MODEL}")
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