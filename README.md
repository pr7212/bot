# JARVIS — Local Autonomous AI Agent

**A locally hosted AI assistant designed to plan, write code, execute commands, interact with the desktop, debug applications, and automate development workflows.**

JARVIS is a Python-based AI agent powered by [Ollama](https://ollama.com/). Its goal is to evolve from a conversational assistant into an autonomous development system capable of completing software engineering tasks with minimal human intervention.

The project prioritizes local AI models, modular architecture, controlled tool execution, and extensibility.

> **Status:** early and experimental. Many components are implemented but not yet verified across a range of real tasks. See the [roadmap](#development-roadmap) for an honest picture.

---

## Project Vision

The long-term goal is to build an AI assistant that can receive a high-level instruction, understand the objective, break it into smaller tasks, implement a solution, execute it, identify errors, and improve its work.

For example:

> Build a complete task management application, test it, fix any errors, and explain how to run it.

JARVIS should eventually be able to:

1. Understand the user's objective.
2. Inspect the project workspace.
3. Create an implementation plan.
4. Write and modify source code.
5. Execute development commands.
6. Run automated tests.
7. Inspect errors and debug problems.
8. Interact with desktop applications.
9. Remember project progress.
10. Report completed work and remaining issues.

## Technology Stack

| Technology                     | Purpose                                   |
| ------------------------------ | ----------------------------------------- |
| Python                         | Main application and agent orchestration  |
| Ollama                         | Local AI model runtime                    |
| Qwen3 8B                       | Reasoning and tool orchestration          |
| Qwen3-VL 4B                    | Visual screen understanding               |
| PyAutoGUI                      | Mouse and keyboard automation             |
| Pillow                         | Screenshot and image handling             |
| SQLite (via `agent/memory.py`) | Persistent notes and task history         |
| Git                            | Version control and automatic checkpoints |

### Local AI Models

- `qwen3:8b` — main reasoning and tool-calling model.
- `qwen3-vl:4b` — visual understanding of the screen.
- `qwen2.5-coder:1.5b` — coding model experimentation (not used by the agent loop yet).

Models can be changed as the project evolves. If the reasoning model and the vision model do not both fit in memory, Ollama will unload and reload them on every screen observation, which is slow. Check with `ollama ps`, and consider setting `OLLAMA_MAX_LOADED_MODELS=2` if your hardware allows it.

## How the Agent Works

Each instruction runs a bounded loop:

1. **Plan.** For non-trivial tasks, one reasoning-enabled call writes a checklist to `PLAN.md` in the workspace. An unfinished plan can be resumed on the next run.
2. **Act.** The model calls tools (file, terminal, memory, desktop). Tool arguments are validated and type-coerced before anything is executed or approved.
3. **Verify.** If files changed, the agent is not allowed to report success until a run or test command has passed. It is sent back to test up to twice.
4. **Checkpoint.** After any step that changed files, everything is committed to a git repository inside the workspace, so every change can be reviewed or rolled back.
5. **Report.** The agent summarizes what was done, how it was verified, and what remains.

Guards: step limit, tool-call limit, repeated-call detection, output clipping, context compaction, an emergency stop file, and a keyboard interrupt.

## Architecture

```text
JARVIS
│
├── AI Engine
│   └── Ollama
│       ├── Qwen3 8B
│       ├── Qwen3-VL 4B
│       └── Qwen2.5-Coder 1.5B
│
├── Agent (autonomous_agent.py)
│   ├── Planning (PLAN.md)
│   ├── Tool orchestration and validation
│   ├── Verification gate
│   └── Memory (agent/memory.py)
│
├── Tools
│   ├── Computer control   (tools/computer.py)
│   ├── Screen analysis    (tools/screen.py)
│   ├── Terminal execution (tools/terminal.py)
│   └── Workspace files    (tools/workspace.py)
│
├── Projects
│   └── agent-test   (workspace, with its own git history)
│
└── Screenshots
```

## Project Structure

```text
bot/
│
├── autonomous_agent.py
│
├── agent/
│   ├── __init__.py
│   └── memory.py
│
├── tools/
│   ├── __init__.py
│   ├── computer.py
│   ├── screen.py
│   ├── terminal.py
│   └── workspace.py
│
├── projects/
│   └── agent-test/        # JARVIS workspace (separate git repo, auto-created)
│       └── PLAN.md        # current task checklist
│
├── screenshots/
├── tests/
├── venv/
├── requirements.txt
├── .gitignore
└── README.md
```

_The structure above describes the intended organization; individual files and capabilities may change during development._

## Requirements

- Windows 10 or Windows 11
- Python 3.10+
- Ollama installed and running
- Git (also used by JARVIS for checkpoints)
- Sufficient RAM/VRAM and disk space for the selected local models

## Installation

### 1. Clone the repository

```powershell
git clone https://github.com/pr7212/bot.git
cd bot
```

### 2. Create a virtual environment

```powershell
python -m venv venv
```

### 3. Activate the environment

```powershell
.\venv\Scripts\Activate.ps1
```

If PowerShell blocks activation:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```

Then activate again.

### 4. Install dependencies

```powershell
python -m pip install --upgrade pip
pip install ollama pyautogui pillow pygetwindow pyperclip python-dotenv
```

### 5. Install Ollama models

```powershell
ollama pull qwen3:8b
ollama pull qwen3-vl:4b
ollama pull qwen2.5-coder:1.5b
```

### 6. Keep the workspace out of the main repository

JARVIS creates a separate git repository inside `projects/agent-test` for its own checkpoints. Add this line to the main repository's `.gitignore` so the two do not interfere:

```text
projects/
screenshots/
```

### 7. Verify installation

```powershell
ollama list
python --version
python -m py_compile .\autonomous_agent.py
```

## Running JARVIS

```powershell
python autonomous_agent.py
```

Example task:

```text
Build a Python calculator application.

Include:
- Addition
- Subtraction
- Multiplication
- Division
- Input validation
- Error handling
- Automated tests

Run the tests and fix any errors.
```

### Console commands

| Command    | Effect                                                      |
| ---------- | ----------------------------------------------------------- |
| `/exit`    | Close JARVIS                                                |
| `/stop`    | Create the emergency stop file (takes effect between tasks) |
| `/resume`  | Clear the emergency stop file                               |
| `/newplan` | Archive the current `PLAN.md` to `PLAN.old.md`              |

While a task is running, stop it with **Ctrl+C**, or create a file named `.jarvis_stop` inside the workspace from a second terminal.

## Configuration

Settings are constants near the top of `autonomous_agent.py`.

| Setting                       | Default    | Meaning                                                          |
| ----------------------------- | ---------- | ---------------------------------------------------------------- |
| `MODEL`                       | `qwen3:8b` | Reasoning model                                                  |
| `NUM_CTX`                     | `16384`    | Context window sent to Ollama. Lower it if you run out of memory |
| `MAX_STEPS`                   | `30`       | Model turns per instruction                                      |
| `MAX_TOOL_CALLS`              | `80`       | Tool calls per instruction                                       |
| `AUTO_PLAN`                   | `True`     | Generate a `PLAN.md` checklist for non-trivial tasks             |
| `AUTO_APPROVE_FILE_CHANGES`   | `True`     | File edits need no prompt (git is the undo)                      |
| `AUTO_APPROVE_COMMANDS`       | `False`    | Every command asks first. Set `True` only inside an isolated VM  |
| `CONFIRM_MEMORY_WRITES`       | `False`    | Ask before saving notes and tasks                                |
| `JARVIS_ENABLE_DESKTOP` (env) | `0`        | Real mouse and keyboard control                                  |

## Computer Automation

JARVIS includes computer-control functionality through PyAutoGUI:

- Capturing screenshots
- Moving the mouse, clicking, right-clicking, double-clicking, dragging
- Typing text and pressing keys or shortcuts
- Scrolling
- Opening desktop applications
- Analyzing visible screen content with the local vision model

Desktop control is **disabled by default**. To enable it for one session:

```powershell
$env:JARVIS_ENABLE_DESKTOP="1"
python autonomous_agent.py
```

Every desktop action requires your approval, and after each action the screen is re-analyzed so the model sees the result before choosing the next step. PyAutoGUI's fail-safe is on: **move the mouse to the top-left corner of the screen to abort.**

**Warning:** Computer control interacts with the real Windows desktop. Use a dedicated test environment and avoid exposing sensitive applications.

## Testing

Check Python syntax:

```powershell
python -m py_compile .\autonomous_agent.py
```

Check tool imports:

```powershell
python -c "from tools import computer, screen, terminal, workspace; print('JARVIS tools loaded')"
```

Run the project's tests if available:

```powershell
python -m unittest discover -s tests -v
```

Individual applications created by JARVIS should also be tested independently.

### Suggested benchmark tasks

To measure progress rather than guess, keep a small set of tasks and re-run them after every change:

1. Create a function plus unit tests, run them, and report the result.
2. Fix a deliberately seeded bug in an existing file.
3. Add an endpoint to a small existing app and test it.
4. Resume an interrupted task from `PLAN.md`.

## Safety and Permissions

Autonomous execution introduces real risks. JARVIS is being developed with the following principles:

- Restrict file operations to an assigned workspace.
- Commit the workspace to git after every step that changes files, so changes are reviewable and reversible.
- Prefer small exact-snippet edits over whole-file rewrites.
- Require approval for every command and every desktop action.
- Allow only a fixed set of executables (`python`, `node`, `npm`, `npx`, `git`, `php`), without a shell.
- Cap command timeouts.
- Validate tool arguments before asking for approval.
- Avoid accessing unrelated personal files.
- Keep desktop control disabled unless explicitly enabled.
- Do not perform purchases, financial transactions, or submit sensitive information autonomously.

**Important:** Workspace restrictions and command allowlists are safeguards, not a complete security sandbox. An allowed command such as `python -c` or an npm script can run arbitrary code, so the approval prompt is the real protection. Generated code can still cause damage. A dedicated virtual machine or properly isolated execution environment is planned for stronger isolation, and `AUTO_APPROVE_COMMANDS` should stay `False` until then.

## Development Roadmap

The project is under active development.

- [x] Establish a Python-based local AI project.
- [x] Integrate Ollama.
- [x] Experiment with local reasoning and coding models.
- [x] Implement computer-control utilities.
- [x] Implement screenshot capture and screen analysis.
- [x] Implement terminal and workspace utilities.
- [x] Implement tool-argument validation, output clipping, and context compaction.
- [x] Implement exact-snippet file editing and git checkpoints.
- [x] Implement a verification gate and repeated-call detection.
- [x] Implement plan files and persistent notes/tasks injected into each run.
- [ ] Verify tool orchestration on a benchmark task set.
- [ ] Improve planning and task decomposition on larger projects.
- [ ] Measure the build → test → fix loop success rate.
- [ ] Add browser automation.
- [ ] Build a dedicated isolated execution environment.
- [ ] Add a graphical user interface.
- [ ] Support larger multi-project development tasks.

_Checked items represent implemented components, not necessarily production-verified capabilities._

## Future Goal

The ultimate objective is to build a local AI development assistant capable of working through complex software projects.

A future version should be able to:

- Build full-stack applications.
- Create and manage databases.
- Develop REST APIs.
- Build frontend interfaces.
- Execute tests.
- Debug applications.
- Inspect browser output.
- Automate repetitive computer tasks.
- Maintain project context.
- Resume interrupted development tasks.

The intention is not simply to create another chatbot, but to develop an AI system that can take meaningful action and verify its results.

Local models have real limits. Reliability will come from good tools, testing, memory, safeguards, and iteration, not from model size alone.

## Contributing

JARVIS is an evolving personal engineering project.

Suggestions, experiments, improvements, and bug reports are welcome.

## Author

**Isaac Ranah**

GitHub: [@pr7212](https://github.com/pr7212)

Repository: [pr7212/bot](https://github.com/pr7212/bot)

---

**JARVIS — Think. Plan. Execute. Verify.**
