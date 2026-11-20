import tempfile
import unittest
from pathlib import Path

from agent.memory import MemoryStore


class MemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "database" / "memory.db"
        self.store = MemoryStore(self.db_path)

    def tearDown(self):
        self.store.close()
        self.temp_dir.cleanup()

    def test_memories_persist_and_can_be_filtered(self):
        self.store.save_memory(
            "preference", "Use TypeScript", project="task-app"
        )
        self.store.save_memory(
            "decision", "Use SQLite", project="jarvis"
        )
        self.store.close()

        with MemoryStore(self.db_path) as reopened:
            memories = reopened.list_memories(
                kind="preference", project="task-app"
            )

        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0]["content"], "Use TypeScript")

    def test_task_status_tracks_completed_and_outstanding_work(self):
        task_id = self.store.create_task(
            "Add screen capture", details="Capture a screenshot.", project="jarvis"
        )
        self.store.create_task("Add screen analysis")
        self.store.update_task_status(task_id, "completed")

        self.assertEqual(len(self.store.list_tasks()), 2)
        outstanding = self.store.list_tasks(outstanding_only=True)
        self.assertEqual([task["title"] for task in outstanding], ["Add screen analysis"])

    def test_invalid_values_and_missing_tasks_raise(self):
        with self.assertRaises(ValueError):
            self.store.save_memory("unknown", "content")
        with self.assertRaises(ValueError):
            self.store.create_task(" ")
        with self.assertRaises(ValueError):
            self.store.update_task_status(1, "unknown")
        with self.assertRaises(LookupError):
            self.store.update_task_status(1, "completed")
        with self.assertRaises(ValueError):
            self.store.list_memories(limit=0)


if __name__ == "__main__":
    unittest.main()
