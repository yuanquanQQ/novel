import asyncio
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
        tasks._OPERATIONS.clear()

    def tearDown(self):
        tasks._TASKS.clear()
        tasks._LOCKS.clear()
        tasks._OPERATIONS.clear()
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
        with patch.object(tasks, "_pid_alive", return_value=False):
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

    def test_persist_reload_keeps_live_process_running_and_locked(self):
        task = {
            "id": "live", "novel": "book", "action": "outline", "args": [],
            "steps": [{"action": "outline", "args": []}], "status": "running",
            "lines": ["开始\n"], "done_steps": 0, "started": 1.0,
            "finished": None, "pid": 456, "_proc": None,
            "cancel_requested": False,
        }
        tasks._TASKS[task["id"]] = task
        tasks._persist(task)
        tasks._TASKS.clear()

        with patch.object(tasks, "_pid_alive", return_value=True):
            tasks._load_history()
            restored = tasks.get("live")
            self.assertEqual(restored["status"], "running")
            self.assertEqual(restored["pid"], 456)
            self.assertEqual(tasks.running_task("book"), "live")
            with self.assertRaises(tasks.BusyError):
                tasks.submit("book", "db", [])

        state = json.loads((tasks.TASKS_DIR / "live.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "running")

    def test_events_cursor_survives_log_trimming(self):
        task = {
            "id": "stream", "novel": "book", "action": "db", "args": [],
            "steps": [], "status": "running", "lines": ["0\n", "1\n", "2\n"],
            "log_start": 0, "done_steps": 0, "started": 1.0,
            "finished": None, "pid": None, "_proc": None,
            "cancel_requested": False,
        }
        tasks._TASKS[task["id"]] = task

        async def consume():
            stream = tasks.events("stream")
            received = [await stream.__anext__()]
            with patch.object(tasks, "MAX_LOG_LINES", 3):
                tasks._append(task, "3\n")
                tasks._append(task, "4\n")
            task["status"] = "done"
            async for line in stream:
                received.append(line)
            return received

        self.assertEqual(
            asyncio.run(consume()),
            ["0\n", "1\n", "2\n", "3\n", "4\n", "__TASK_END__ done"],
        )

    def test_cancel_reports_false_when_completion_wins_race(self):
        task = {
            "id": "race", "novel": "book", "action": "outline", "args": [],
            "steps": [], "status": "running", "lines": [], "done_steps": 0,
            "started": 1.0, "finished": None, "pid": 456,
            "_proc": Mock(pid=456), "cancel_requested": False,
        }
        tasks._TASKS[task["id"]] = task

        def complete_first(pid, proc):
            task["status"] = "done"

        with patch.object(tasks, "_terminate_process_tree", side_effect=complete_first):
            result = tasks.cancel("race")

        self.assertFalse(result["cancelled"])
        self.assertEqual(result["status"], "done")
        self.assertNotIn("[取消]", "".join(task["lines"]))

    def test_atomic_text_retries_permission_error(self):
        target = tasks.TASKS_DIR / "state.json"
        with (patch.object(tasks.os, "replace",
                           side_effect=[PermissionError(), PermissionError(), None]) as replace,
              patch.object(tasks.time, "sleep") as sleep):
            tasks._atomic_text(target, "{}")
        self.assertEqual(replace.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_failed_step_is_not_counted_as_done(self):
        task = {
            "id": "steps", "novel": "book", "action": "pipeline", "args": [],
            "steps": [
                {"action": "outline", "args": []},
                {"action": "write", "args": []},
            ],
            "status": "running", "lines": [], "log_start": 0, "done_steps": 0,
            "failed_step": None, "started": 1.0, "finished": None, "pid": None,
            "_proc": None, "cancel_requested": False,
        }
        tasks._TASKS[task["id"]] = task
        tasks._LOCKS["book"] = task["id"]

        with patch.object(tasks, "_run_step", side_effect=[0, 7]):
            tasks._worker(task["id"])

        self.assertEqual(task["status"], "failed")
        self.assertEqual(task["done_steps"], 1)
        self.assertEqual(task["failed_step"], 2)

    def test_operation_guard_and_submit_are_mutually_exclusive(self):
        with tasks.novel_guard("book"):
            with self.assertRaises(tasks.BusyError):
                tasks.submit("book", "db", [])
        task = {"id": "active", "novel": "book", "status": "running"}
        tasks._TASKS["active"] = task
        tasks._LOCKS["book"] = "active"
        with self.assertRaises(tasks.BusyError):
            with tasks.novel_guard("book"):
                pass


if __name__ == "__main__":
    unittest.main()
