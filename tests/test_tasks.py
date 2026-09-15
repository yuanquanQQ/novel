import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from server import tasks


class TaskPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved_dir = tasks.TASKS_DIR
        tasks.TASKS_DIR = Path(self.tmp.name) / "tasks"
        tasks._TASKS.clear()
        tasks._LOCKS.clear()

    def tearDown(self):
        tasks._TASKS.clear()
        tasks._LOCKS.clear()
        tasks.TASKS_DIR = self.saved_dir
        self.tmp.cleanup()

    def test_persist_reload_marks_running_orphaned(self):
        task = {
            "id": "persisted", "novel": "book", "action": "outline", "args": [],
            "steps": [{"action": "outline", "args": []}], "status": "running",
            "lines": ["开始\n"], "done_steps": 0, "started": 1.0,
            "finished": None, "pid": 123, "_proc": None,
            "cancel_requested": False,
        }
        tasks._TASKS[task["id"]] = task
        tasks._persist(task)
        tasks._TASKS.clear()
        tasks._load_history()
        restored = tasks.get("persisted")
        self.assertEqual(restored["status"], "orphaned")
        self.assertIsNone(restored["pid"])
        self.assertIn("orphaned", "".join(restored["lines"]))
        state = json.loads((tasks.TASKS_DIR / "persisted.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "orphaned")

    def test_log_memory_is_bounded(self):
        task = {
            "id": "bounded", "novel": "book", "action": "db", "args": [],
            "steps": [], "status": "done", "lines": [], "done_steps": 0,
            "started": 1.0, "finished": 2.0, "pid": None,
            "_proc": None, "cancel_requested": False,
        }
        tasks._TASKS[task["id"]] = task
        with patch.object(tasks, "MAX_LOG_LINES", 5):
            for number in range(8):
                tasks._append(task, f"{number}\n")
        self.assertEqual(task["lines"], ["3\n", "4\n", "5\n", "6\n", "7\n"])

    def test_cancel_terminates_process_tree_and_persists(self):
        proc = Mock(pid=456)
        task = {
            "id": "running", "novel": "book", "action": "outline", "args": [],
            "steps": [], "status": "running", "lines": [], "done_steps": 0,
            "started": 1.0, "finished": None, "pid": 456,
            "_proc": proc, "cancel_requested": False,
        }
        tasks._TASKS[task["id"]] = task
        tasks._LOCKS["book"] = task["id"]
        with patch.object(tasks, "_terminate_process_tree") as terminate:
            result = tasks.cancel("running")
        terminate.assert_called_once_with(456, proc)
        self.assertTrue(result["cancelled"])
        self.assertEqual(task["status"], "cancelled")
        self.assertEqual(tasks.running_task("book"), "running")
        with self.assertRaises(tasks.BusyError):
            tasks.submit("book", "db", [])
        tasks._release(task)
        self.assertIsNone(tasks.running_task("book"))
        state = json.loads((tasks.TASKS_DIR / "running.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
