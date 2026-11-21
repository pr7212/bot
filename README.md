# JARVIS — Local Autonomous AI Agent

**A locally hosted AI assistant designed to plan, write code, execute commands, interact with the desktop, debug applications, and automate development workflows.**

JARVIS is a Python-based AI agent powered by [Ollama](https://ollama.com/). Its goal is to evolve from a conversational assistant into an autonomous development system capable of completing software engineering tasks with minimal human intervention.

The project prioritizes local AI models, modular architecture, controlled tool execution, and extensibility.

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

| Technology   | Purpose                                  |
| ------------ | ---------------------------------------- |
| Python       | Main application and agent orchestration |
| Ollama       | Local AI model runtime                   |
| Qwen3 8B     | Reasoning and tool orchestration         |
| Qwen3-VL 4B  | Visual screen understanding              |
| PyAutoGUI    | Mouse and keyboard automation            |
| Pillow       | Screenshot and image handling            |
| PowerShell   | Windows command execution                |
| Git & GitHub | Version control                          |

### Local AI Models

Models currently used or available for experimentation:

- `qwen3:8b` — Main reasoning model.
- `qwen3-vl:4b` — Visual understanding.
- `qwen2.5-coder:1.5b` — Coding model experimentation.

Models can be changed as the project evolves.

## Architecture

JARVIS is organized around independent tools coordinated by an AI agent.

```text
JARVIS
│
├── AI Engine
│   └── Ollama
│       ├── Qwen3 8B
│       ├── Qwen3-VL 4B
│       └── Qwen2.5-Coder 1.5B
│
├── Agent
│   ├── Planning
│   ├── Tool orchestration
│   ├── Task execution
│   └── Memory
│
├── Tools
│   ├── Computer control
│   ├── Screen analysis
│   ├── Terminal execution
│   └── Workspace management
│
├── Projects
│   └── agent-test
│
├── Screenshots
│
└── autonomous_agent.py
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
│   └── agent-test/
│
├── screenshots/
│
├── tests/
│
├── venv/
│
├── .gitignore
└── README.md
```

_The structure above describes the intended organization; individual files and capabilities may change during development._

## Requirements

- Windows 10 or Windows 11
- Python 3.10+
- Ollama installed
- Git
- Sufficient RAM and disk space for the selected local models

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
pip install ollama pyautogui pillow pygetwindow python-dotenv
```

### 5. Install Ollama models

```powershell
ollama pull qwen3:8b
ollama pull qwen3-vl:4b
ollama pull qwen2.5-coder:1.5b
```

### 6. Verify installation

```powershell
ollama list
python --version
python -m py_compile .\autonomous_agent.py
```

## Running JARVIS

Start the agent:

```powershell
python autonomous_agent.py
```

The agent should accept a natural-language instruction through its command-line interface.

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

JARVIS should use its available tools to work within the configured project workspace.

## Computer Automation

JARVIS includes computer-control functionality through PyAutoGUI.

Potential capabilities include:

- Capturing screenshots.
- Moving the mouse.
- Clicking interface elements.
- Typing text.
- Pressing keyboard shortcuts.
- Scrolling.
- Opening desktop applications.
- Analyzing visible screen content.

Desktop control is disabled by default in the autonomous agent integration.

To enable it when supported by the current implementation:

```powershell
$env:JARVIS_ENABLE_DESKTOP="1"
python autonomous_agent.py
```

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

## Safety and Permissions

Autonomous execution introduces real risks. JARVIS is being developed with the following principles:

- Restrict file operations to an assigned workspace.
- Avoid overwriting existing files without appropriate safeguards.
- Back up files before modifying them.
- Require approval for potentially dangerous operations.
- Limit command execution.
- Use timeouts for subprocesses.
- Avoid accessing unrelated personal files.
- Keep desktop control disabled unless explicitly needed.
- Do not perform purchases, financial transactions, or submit sensitive information autonomously.

**Important:** Workspace restrictions and command allowlists are safeguards, not a complete security sandbox. Generated Python code and permitted commands can still cause damage. A dedicated virtual machine or properly isolated execution environment is planned for stronger isolation.

## Development Roadmap

The project is under active development.

- [x] Establish a Python-based local AI project.
- [x] Integrate Ollama.
- [x] Experiment with local reasoning and coding models.
- [x] Implement computer-control utilities.
- [x] Implement screenshot capture and screen analysis.
- [x] Implement terminal and workspace utilities.
- [ ] Complete reliable autonomous tool orchestration.
- [ ] Improve planning and task decomposition.
- [ ] Implement reliable file-editing and backup workflows.
- [ ] Implement automated testing and debugging loops.
- [ ] Improve persistent memory and task recovery.
- [ ] Add browser automation.
- [ ] Build a dedicated isolated execution environment.
- [ ] Add a graphical user interface.
- [ ] Support larger multi-project development tasks.

_Checked items represent implemented components or existing experiments, not necessarily fully integrated or production-verified capabilities._

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

## Contributing

JARVIS is an evolving personal engineering project.

Suggestions, experiments, improvements, and bug reports are welcome.

## Author

**Isaac Ranah**

GitHub: [@pr7212](https://github.com/pr7212)

Repository: [pr7212/bot](https://github.com/pr7212/bot)

---

**JARVIS — Think. Plan. Execute. Verify.**
