import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import jarvis
from agent.memory import MemoryStore


class JarvisMemoryToolTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "memory.db"
        self.store_patch = patch(
            "jarvis.MemoryStore",
            side_effect=lambda: MemoryStore(self.db_path),
        )
        self.store_patch.start()

    def tearDown(self):
        self.store_patch.stop()
        self.temp_dir.cleanup()

    @staticmethod
    def tool_call(name, arguments):
        return SimpleNamespace(
            function=SimpleNamespace(name=name, arguments=arguments)
        )

    def test_memory_tools_are_registered_and_round_trip_data(self):
        self.assertIn("save_memory", jarvis.AVAILABLE_FUNCTIONS)
        self.assertIn("list_memories", jarvis.AVAILABLE_FUNCTIONS)
        self.assertIn("create_task", jarvis.AVAILABLE_FUNCTIONS)
        self.assertIn("update_task_status", jarvis.AVAILABLE_FUNCTIONS)
        self.assertIn("list_tasks", jarvis.AVAILABLE_FUNCTIONS)

        with patch("builtins.input", return_value="y"):
            saved = jarvis.execute_tool(
                self.tool_call(
                    "save_memory",
                    {
                        "kind": "decision",
                        "content": "Use SQLite for local memory",
                        "project": "jarvis",
                    },
                )
            )
            task = jarvis.execute_tool(
                self.tool_call("create_task", {"title": "Connect memory tools"})
            )
        task_id = json.loads(task)["id"]
        with patch("builtins.input", return_value="y"):
            updated_task = jarvis.execute_tool(
                self.tool_call(
                    "update_task_status",
                    {"task_id": task_id, "status": "in_progress"},
                )
            )

        memories = json.loads(
            jarvis.execute_tool(
                self.tool_call("list_memories", {"project": "jarvis"})
            )
        )
        tasks = json.loads(
            jarvis.execute_tool(
                self.tool_call("list_tasks", {"outstanding_only": True})
            )
        )
        all_tasks = json.loads(
            jarvis.execute_tool(self.tool_call("list_tasks", {}))
        )

        self.assertTrue(json.loads(saved)["saved"])
        self.assertEqual(memories[0]["content"], "Use SQLite for local memory")
        self.assertEqual(tasks[0]["id"], task_id)
        self.assertEqual(json.loads(updated_task)["status"], "in_progress")
        self.assertEqual(all_tasks[0]["status"], "in_progress")

    def test_memory_writes_are_denied_without_approval(self):
        with patch("builtins.input", return_value="n"):
            result = jarvis.execute_tool(
                self.tool_call(
                    "save_memory",
                    {"kind": "preference", "content": "Use dark mode"},
                )
            )

        self.assertEqual(result, "Action denied by user.")
        self.assertEqual(jarvis.list_memories(), [])


if __name__ == "__main__":
    unittest.main()
