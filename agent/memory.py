"""Persistent local memory for JARVIS tasks and project notes."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB_PATH = (
    Path(__file__).resolve().parent.parent / "database" / "memory.db"
)

MEMORY_KINDS = frozenset(
    {"project_structure", "decision", "preference", "note"}
)
TASK_STATUSES = frozenset(
    {"planned", "in_progress", "completed", "blocked"}
)


def _validate_text(value, name, allow_empty=False):
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"{name} must be a non-empty string.")
    return value


class MemoryStore:
    """Store task history and durable project notes in a local SQLite database."""

    def __init__(self, db_path=DEFAULT_DB_PATH):
        if str(db_path) == ":memory:":
            self.db_path = ":memory:"
        else:
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._connection = sqlite3.connect(str(self.db_path), timeout=5)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY,
                kind TEXT NOT NULL CHECK (
                    kind IN ('project_structure', 'decision', 'preference', 'note')
                ),
                content TEXT NOT NULL,
                project TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL CHECK (
                    status IN ('planned', 'in_progress', 'completed', 'blocked')
                ),
                project TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS memories_project_kind_idx
                ON memories(project, kind);
            CREATE INDEX IF NOT EXISTS tasks_status_updated_idx
                ON tasks(status, updated_at);
            """
        )
        self._connection.commit()

    def close(self):
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    @staticmethod
    def _timestamp():
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _validate_limit(limit):
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("limit must be a positive integer.")

    def save_memory(self, kind, content, project=None):
        if not isinstance(kind, str) or kind not in MEMORY_KINDS:
            raise ValueError(f"kind must be one of: {', '.join(sorted(MEMORY_KINDS))}.")
        _validate_text(content, "content")
        if project is not None:
            _validate_text(project, "project")

        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO memories (kind, content, project, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (kind, content, project, self._timestamp()),
            )
        return cursor.lastrowid

    def list_memories(self, kind=None, project=None, limit=100):
        self._validate_limit(limit)
        filters = []
        values = []

        if kind is not None:
            if not isinstance(kind, str) or kind not in MEMORY_KINDS:
                raise ValueError(
                    f"kind must be one of: {', '.join(sorted(MEMORY_KINDS))}."
                )
            filters.append("kind = ?")
            values.append(kind)
        if project is not None:
            _validate_text(project, "project")
            filters.append("project = ?")
            values.append(project)

        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        rows = self._connection.execute(
            f"""
            SELECT id, kind, content, project, created_at
            FROM memories
            {where}
            ORDER BY id DESC
            LIMIT ?
            """,
            (*values, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def create_task(self, title, details="", project=None):
        _validate_text(title, "title")
        _validate_text(details, "details", allow_empty=True)
        if project is not None:
            _validate_text(project, "project")

        now = self._timestamp()
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO tasks
                    (title, details, status, project, created_at, updated_at)
                VALUES (?, ?, 'planned', ?, ?, ?)
                """,
                (title, details, project, now, now),
            )
        return cursor.lastrowid

    def update_task_status(self, task_id, status):
        if not isinstance(task_id, int) or isinstance(task_id, bool) or task_id < 1:
            raise ValueError("task_id must be a positive integer.")
        if not isinstance(status, str) or status not in TASK_STATUSES:
            raise ValueError(
                f"status must be one of: {', '.join(sorted(TASK_STATUSES))}."
            )

        with self._connection:
            cursor = self._connection.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                (status, self._timestamp(), task_id),
            )
        if cursor.rowcount == 0:
            raise LookupError(f"Task not found: {task_id}")

    def list_tasks(self, outstanding_only=False, limit=100):
        self._validate_limit(limit)
        if not isinstance(outstanding_only, bool):
            raise ValueError("outstanding_only must be a boolean.")

        where = "WHERE status != 'completed'" if outstanding_only else ""
        rows = self._connection.execute(
            f"""
            SELECT id, title, details, status, project, created_at, updated_at
            FROM tasks
            {where}
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
