import json
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

SYSTEM = (
    "You are a helpful assistant. When the user asks you to perform an "
    "action that matches an available tool, call that tool directly. "
    "Do not explain or output code."
)

def debug_chat(model, messages, tools=TOOLS, **kwargs):
    print(f"\n{'='*60}\nMODEL: {model}\n{'='*60}")
    try:
        resp = ollama.chat(model=model, messages=messages, tools=tools, **kwargs)
    except Exception as e:
        print(f"[ERROR calling model] {type(e).__name__}: {e}")
        return None

    msg = resp.message
    print(f"role            : {msg.role}")
    print(f"tool_calls      : {msg.tool_calls!r}")
    print(f"content (repr)  : {msg.content!r}")
    print(f"raw message dict: {msg.model_dump()}")

    # Diagnostics
    if msg.tool_calls:
        for tc in msg.tool_calls:
            fn = tc.function
            print(f"  -> name={fn.name!r}  args={fn.arguments!r} (type={type(fn.arguments).__name__})")
            if fn.name != "open_notepad":
                print(f"  [WARN] hallucinated tool name: {fn.name!r}")
    else:
        c = (msg.content or "")
        lowered = c.lower()
        if "open_notepad" in lowered or "{" in c:
            print("  [DIAG] content looks like it *contains* a tool call in text — "
                  "chat template likely not parsing tool calls.")
        elif "notepad" in lowered and any(w in lowered for w in ("can't", "cannot", "unable", "don't have")):
            print("  [DIAG] model refused — likely no system prompt nudging tool use.")
        elif "import" in lowered or "subprocess" in lowered or "os.startfile" in lowered:
            print("  [DIAG] model wrote code instead of calling the tool "
                  "(common with coder models).")
        else:
            print("  [DIAG] no tool call, generic text response.")

    # Check the raw API payload too
    print(f"model echo      : {resp.model}  done={resp.done}  "
          f"eval_count={getattr(resp, 'eval_count', '?')}")
    return resp


if __name__ == "__main__":
    for model in ["qwen2.5-coder:1.5b", "qwen3:8b"]:
        # Test 1: bare user prompt (your original)
        debug_chat(model, [{"role": "user", "content": "Open notepad."}])

        # Test 2: with system prompt
        debug_chat(model, [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": "Open notepad."},
        ])
