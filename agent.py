
import json
import shutil
import ollama

from datetime import datetime
from pathlib import Path

MODEL = "qwen2.5-coder:1.5b"

WORKSPACE = Path(__file__).resolve().parent
BACKUP_DIR = WORKSPACE / ".agent_backups"

MAX_FILES_PER_TASK = 5
MAX_FILE_SIZE = 15000
MAX_PROJECT_FILES = 20
MAX_CONTEXT_SIZE = 24000


def safe_path(filename):
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("Invalid filename.")

    path = (WORKSPACE / filename).resolve()
    path.relative_to(WORKSPACE)

    if path == WORKSPACE:
        raise ValueError("Invalid file location.")

    if path == BACKUP_DIR or BACKUP_DIR in path.parents:
        raise ValueError("Cannot edit backup files.")

    return path


def inspect_project():
    """Read existing project files and provide context to the AI."""

    print("\nInspecting existing project files...")

    ignored = {
        "venv",
        ".venv",
        "__pycache__",
        ".git",
        ".agent_backups"
    }

    excluded_files = {
        "agent.py",
        "main.py",
        "executor.py"
    }

    project_files = []

    for path in WORKSPACE.rglob("*.py"):

        if any(part in ignored for part in path.parts):
            continue

        if path.name in excluded_files:
            continue

        if not path.is_file():
            continue

        project_files.append(path)

        if len(project_files) >= MAX_PROJECT_FILES:
            break

    context = []
    total_size = 0

    for path in project_files:
        try:
            content = path.read_text(
                encoding="utf-8",
                errors="replace"
            )

            relative = str(path.relative_to(WORKSPACE))

            section = (
                f"\n--- EXISTING FILE: {relative} ---\n"
                f"{content}\n"
            )

            if total_size + len(section) > MAX_CONTEXT_SIZE:
                print("Project context limit reached.")
                break

            context.append(section)
            total_size += len(section)

        except OSError as error:
            print(f"Could not read {path.name}: {error}")

    if not context:
        print("No existing Python project files found.")
        return "No existing project files."

    print(f"Loaded {len(context)} project files.")

    return "\n".join(context)


def create_plan(instruction, project_context):

    messages = [
        {
            "role": "system",
            "content": """
You are a senior software architect.

Create a practical implementation plan.

IMPORTANT:
- Follow the user's requested application type.
- If they request a CLI, build a CLI.
- Do not introduce unrequested frameworks.
- Build one integrated application.
- Reuse existing files where appropriate.
- Avoid duplicate files.
- Each task must describe a working implementation.
- Keep tasks small and achievable.

Return ONLY JSON:

{
  "project": "Project name",
  "tasks": [
    {
      "id": 1,
      "title": "Task title",
      "description": "Detailed implementation instructions"
    }
  ]
}

Create between 3 and 8 tasks in implementation order.
"""
        },
        {
            "role": "user",
            "content": (
                f"USER REQUIREMENTS:\n{instruction}\n\n"
                f"EXISTING PROJECT:\n{project_context}"
            )
        }
    ]

    print("\nAI is planning your project...")

    response = ollama.chat(
        model=MODEL,
        messages=messages,
        format="json",
        options={
            "temperature": 0.2,
            "num_predict": 1200
        }
    )

    try:
        plan = json.loads(response["message"]["content"])

    except (json.JSONDecodeError, KeyError, TypeError):
        print("Could not understand the AI plan.")
        return None

    if not isinstance(plan, dict):
        return None

    tasks = plan.get("tasks")

    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 8:
        print("Invalid task list.")
        return None

    for item in tasks:

        if not isinstance(item, dict):
            return None

        if not all(
            isinstance(item.get(key), str) and item[key].strip()
            for key in ("title", "description")
        ):
            return None

    return plan


def generate_task(task, project_name):

    project_context = inspect_project()

    messages = [
        {
            "role": "system",
            "content": """
You are an autonomous software engineering coding agent.

Your responsibility is to implement the assigned task
inside an existing software project.

Study the existing project source code first.

RULES:
- Maintain the existing architecture.
- Integrate code with existing files.
- Do not create duplicate files unnecessarily.
- Do not introduce unrequested frameworks.
- For CLI projects, generate CLI Python code.
- Do not generate Django views unless requested.
- Do not use placeholders or TODO implementations.
- Return complete file contents.
- Maximum 5 files per task.
- Do not modify unrelated files.

Return ONLY valid JSON:

{
  "files": [
    {
      "path": "example.py",
      "action": "create",
      "content": "complete file contents"
    }
  ],
  "explanation": "What you implemented"
}

Action must be:
- create: create a new file.
- update: replace an existing file.
"""
        },
        {
            "role": "user",
            "content": (
                f"PROJECT: {project_name}\n\n"
                f"CURRENT TASK:\n{task['title']}\n\n"
                f"INSTRUCTIONS:\n{task['description']}\n\n"
                f"EXISTING PROJECT SOURCE CODE:\n{project_context}"
            )
        }
    ]

    print("\nAI is analyzing the project and generating code...")

    response = ollama.chat(
        model=MODEL,
        messages=messages,
        format="json",
        options={
            "temperature": 0.2,
            "num_predict": 3000
        }
    )

    try:
        result = json.loads(response["message"]["content"])

    except (json.JSONDecodeError, KeyError, TypeError):
        print("AI returned invalid JSON.")
        return None

    if not isinstance(result, dict):
        return None

    files = result.get("files")

    if not isinstance(files, list):
        print("Invalid generated file list.")
        return None

    if not 1 <= len(files) <= MAX_FILES_PER_TASK:
        print("Invalid number of generated files.")
        return None

    validated = []
    seen = set()

    try:

        for item in files:

            if not isinstance(item, dict):
                raise ValueError("Invalid file entry.")

            filename = item.get("path")
            action = item.get("action")
            content = item.get("content")

            if action not in ("create", "update"):
                raise ValueError("Action must be create or update.")

            if not isinstance(content, str):
                raise ValueError("File content must be text.")

            path = safe_path(filename)

            if path.suffix.lower() != ".py":
                raise ValueError("Only Python files are supported.")

            if len(content.encode("utf-8")) > MAX_FILE_SIZE:
                raise ValueError(f"{filename} is too large.")

            if path in seen:
                raise ValueError("Duplicate file path.")

            seen.add(path)

            exists = path.exists()

            if action == "create" and exists:
                raise ValueError(
                    f"{filename} already exists. Use update instead."
                )

            if action == "update" and not exists:
                raise ValueError(
                    f"{filename} does not exist. Use create instead."
                )

            if exists and not path.is_file():
                raise ValueError(f"{filename} is not a regular file.")

            validated.append((path, action, content))

    except (ValueError, OSError, UnicodeError) as error:

        print("File validation failed:", error)
        return None

    print("\nProposed changes:")

    for path, action, content in validated:

        print(f"\n{action.upper()}: {path.relative_to(WORKSPACE)}")
        print(f"New size: {len(content)} characters")

    print("\nAI explanation:")
    print(result.get("explanation", "No explanation supplied."))

    approval = input(
        "\nApprove these file changes? (yes/no): "
    ).strip().lower()

    if approval not in ("yes", "y"):

        print("Changes cancelled.")
        return False

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    backups = []
    created = []

    try:

        for path, action, content in validated:

            path.parent.mkdir(parents=True, exist_ok=True)

            if action == "update":

                BACKUP_DIR.mkdir(parents=True, exist_ok=True)

                backup_path = (
                    BACKUP_DIR
                    / timestamp
                    / path.relative_to(WORKSPACE)
                )

                backup_path.parent.mkdir(
                    parents=True,
                    exist_ok=True
                )

                shutil.copy2(path, backup_path)
                backups.append((path, backup_path))

                path.write_text(
                    content,
                    encoding="utf-8"
                )

            else:

                with path.open("x", encoding="utf-8") as file:

                    created.append(path)
                    file.write(content)

    except (OSError, UnicodeError) as error:

        print("File update failed:", error)

        for path in reversed(created):

            try:
                path.unlink()

            except OSError:
                pass

        for path, backup_path in reversed(backups):

            try:
                shutil.copy2(backup_path, path)

            except OSError as restore_error:

                print(
                    f"Could not restore {path.name}: {restore_error}"
                )

        return False

    print("\nTask changes saved successfully.")

    if backups:
        print("Previous versions saved in .agent_backups.")

    return True


def main():

    print("=" * 45)
    print("       PROJECT-AWARE CODING AGENT")
    print("=" * 45)

    print("\nDescribe the complete software you want to build.")
    print("Enter multiple lines. Type /end when finished.\n")

    lines = []

    while True:

        line = input()

        if line.strip().lower() == "/end":
            break

        lines.append(line)

    instruction = "\n".join(lines).strip()

    if not instruction:

        print("No instruction supplied.")
        return

    try:

        project_context = inspect_project()

        plan = create_plan(instruction, project_context)

        if not plan:
            return

        project_name = plan.get("project", "Untitled Project")

        print("\nDevelopment plan:")

        for item in plan["tasks"]:

            print(f"\n{item.get('id', '?')}. {item['title']}")
            print(item["description"])

        approval = input(
            "\nApprove this development plan? (yes/no): "
        ).strip().lower()

        if approval not in ("yes", "y"):

            print("Plan rejected.")
            return

        for index, task in enumerate(plan["tasks"], start=1):

            print("\n" + "=" * 45)
            print(f"TASK {index}/{len(plan['tasks'])}")
            print(task["title"])
            print("=" * 45)

            result = generate_task(task, project_name)

            if result is not True:

                print(
                    "\nAgent paused. Remaining tasks were not executed."
                )
                return

        print("\nAll planned tasks completed.")

    except KeyboardInterrupt:

        print("\nAgent stopped by user.")

    except Exception as error:

        print(f"\nAgent error: {error}")


if __name__ == "__main__":
    main()
