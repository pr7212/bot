import ollama

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "open_notepad",
            "description": "Launch Windows Notepad.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }
]

for model in ["qwen2.5-coder:1.5b", "qwen3:8b"]:
    response = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": "Open notepad."}],
        tools=TOOLS,
    )
    print(model, "->", response.message.tool_calls)
    print("   content:", repr(response.message.content)[:200])