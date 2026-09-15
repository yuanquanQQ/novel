# 流水线状态 API + 批量任务 steps 测试
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

import engine.novel_creator as novel_creator
import engine.settings as settings
import server.app as server_app
from server import tasks as T


class PipelineTestCase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.novels_dir = Path(self._tmp.name) / "novels"
        self.novels_dir.mkdir()
        self._saved = (novel_creator.NOVELS_DIR, server_app.NOVELS_DIR,
                       settings.NOVELS_DIR)
        novel_creator.NOVELS_DIR = self.novels_dir
        server_app.NOVELS_DIR = self.novels_dir
        settings.NOVELS_DIR = self.novels_dir
        self.client = TestClient(server_app.app)
        r = self.client.post("/api/novels", json={
            "id": "pipe", "title": "流水线", "chapter_count": 8, "words_per_chapter": 2000})
        self.assertEqual(r.status_code, 201, r.text)
        self.book = self.novels_dir / "pipe"

    def write_titles(self, count=8):
        payload = {"volumes": {"volume_1": {"chapters": {
            str(n): f"名{n}" for n in range(1, count + 1)}}}}
        (self.book / "bible" / "chapter_titles.json").write_text(
            json.dumps(payload), encoding="utf-8")

    def tearDown(self):
        (novel_creator.NOVELS_DIR, server_app.NOVELS_DIR,
         settings.NOVELS_DIR) = self._saved
        self._tmp.cleanup()

    def step(self, out, key):
        return [s for s in out["steps"] if s["key"] == key][0]

    def test_fresh_book_stage_outline(self):
        # create_novel 会预写自动章名（第1章…），先清掉模拟"未提取"
        self.write_titles(0)
        out = self.client.get("/api/novels/pipe/pipeline").json()
        self.assertEqual(out["stage"], "outline")
        self.assertEqual(out["next_chapter"], 1)
        self.assertFalse(self.step(out, "outline")["done"])
        self.assertFalse(self.step(out, "titles")["available"])  # 依赖大纲

    def test_titles_unlocked_after_outline(self):
        self.write_titles(0)
        (self.book / "bible" / "outline.md").write_text(
            "- **第1章 起**：开场。*引入*\n- **第2章 变**：转折。*推进*\n", encoding="utf-8")
        out = self.client.get("/api/novels/pipe/pipeline").json()
        self.assertEqual(out["stage"], "titles")
        self.assertTrue(self.step(out, "titles")["available"])
        self.assertEqual(self.step(out, "outline")["detected"], 2)
        self.assertFalse(self.step(out, "write")["available"])

    def test_write_stage(self):
        self.write_titles()
        (self.book / "bible" / "outline.md").write_text("第1章 x", encoding="utf-8")
        out = self.client.get("/api/novels/pipe/pipeline").json()
        self.assertEqual(out["stage"], "write")
        w = self.step(out, "write")
        self.assertTrue(w["available"])
        self.assertEqual(w["detail"]["next_chapter"], 1)
        self.assertEqual(w["detail"]["range"], [1, 8])

    def test_gap_detection_and_next(self):
        self.write_titles()
        (self.book / "bible" / "outline.md").write_text("第1章 x", encoding="utf-8")
        for n in (1, 2, 4):
            (self.book / "generated" / f"chapter_{n:02d}.md").write_text("正文", encoding="utf-8")
        out = self.client.get("/api/novels/pipe/pipeline").json()
        self.assertEqual(out["stage"], "fill_gaps")
        self.assertEqual(out["next_chapter"], 3)
        self.assertEqual(self.step(out, "write")["detail"]["missing"], [3])

    def test_summary_unlock_when_volume_full(self):
        self.write_titles()
        (self.book / "bible" / "outline.md").write_text("第1章 x", encoding="utf-8")
        for n in range(1, 9):
            (self.book / "generated" / f"chapter_{n:02d}.md").write_text("正文", encoding="utf-8")
        out = self.client.get("/api/novels/pipe/pipeline").json()
        self.assertEqual(out["stage"], "volume_summary")
        s = self.step(out, "summary")
        self.assertTrue(s["available"])
        self.assertEqual(s["pending"][0]["key"], "volume_1")
        (self.book / "generated" / "volume_1_summary.md").write_text("总结", encoding="utf-8")
        out = self.client.get("/api/novels/pipe/pipeline").json()
        self.assertEqual(out["stage"], "publish")

    def test_publish_stage_at_end(self):
        self.write_titles()
        (self.book / "bible" / "outline.md").write_text("第1章 x", encoding="utf-8")
        for n in range(1, 9):
            (self.book / "generated" / f"chapter_{n:02d}.md").write_text("正文", encoding="utf-8")
        for v in range(1, 5):
            (self.book / "generated" / f"volume_{v}_summary.md").write_text("总结", encoding="utf-8")
        out = self.client.get("/api/novels/pipe/pipeline").json()
        self.assertEqual(out["stage"], "publish")
        self.assertTrue(self.step(out, "publish")["done"])


class BatchTaskShapeTests(unittest.TestCase):
    """不启动子进程：patch T.submit 捕获参数。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.novels_dir = Path(self._tmp.name) / "novels"
        self.novels_dir.mkdir()
        self._saved = (novel_creator.NOVELS_DIR, server_app.NOVELS_DIR, settings.NOVELS_DIR)
        novel_creator.NOVELS_DIR = self.novels_dir
        server_app.NOVELS_DIR = self.novels_dir
        settings.NOVELS_DIR = self.novels_dir
        self.client = TestClient(server_app.app)
        self.client.post("/api/novels", json={
            "id": "batch", "title": "批量", "chapter_count": 30, "words_per_chapter": 2000})
        self._real_submit = T.submit
        self.captured = {}

        def fake_submit(novel, action, args, steps=None):
            self.captured = {"novel": novel, "action": action, "args": args, "steps": steps}
            return "stub-task"
        T.submit = fake_submit

    def tearDown(self):
        T.submit = self._real_submit
        (novel_creator.NOVELS_DIR, server_app.NOVELS_DIR,
         settings.NOVELS_DIR) = self._saved
        self._tmp.cleanup()

    def test_single_chapter_no_steps(self):
        r = self.client.post("/api/novels/batch/tasks/generate", json={"chapter": 3})
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(self.captured["steps"])
        self.assertEqual(self.captured["args"], ["3"])

    def test_batch_builds_sequential_steps(self):
        r = self.client.post("/api/novels/batch/tasks/generate",
                             json={"chapter": 3, "chapter_end": 6, "prompt": "加快节奏"},
                             )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["steps"], 4)
        self.assertEqual([s["args"][0] for s in self.captured["steps"]],
                         ["3", "4", "5", "6"])
        self.assertTrue(all(s["action"] == "generate" for s in self.captured["steps"]))
        self.assertTrue(all(s["args"][1:3] == ["-p", "加快节奏"] for s in self.captured["steps"]))

    def test_batch_guardrails(self):
        r = self.client.post("/api/novels/batch/tasks/generate",
                             json={"chapter": 1, "chapter_end": 40})   # 超30章总数
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/novels/batch/tasks/generate",
                             json={"chapter": 1, "chapter_end": 25})   # >20章/批
        self.assertEqual(r.status_code, 422)
        r = self.client.post("/api/novels/batch/tasks/generate",
                             json={"chapter": 5, "chapter_end": 2})
        self.assertEqual(r.status_code, 400)


class WorkerStepStopTests(unittest.TestCase):
    """多步任务：第一步失败则停止且不执行后续步骤。"""

    def test_steps_stop_on_failure(self):
        t = {"id": "x", "novel": "n", "action": "generate", "args": [],
             "steps": [{"action": "generate", "args": ["1"]}],
             "status": "running", "lines": [], "done_steps": 0}
        T._TASKS["x"] = t
        calls = []

        def fake_run(task, cmd):
            calls.append(cmd)
            return 1     # 模拟失败
        real = T._run_step
        T._run_step = fake_run
        try:
            T._worker("x")
        finally:
            T._run_step = real
        T._TASKS.pop("x", None)
        self.assertEqual(t["status"], "failed")
        self.assertEqual(len(calls), 1)      # 只执行了一步？steps只有1
        self.assertEqual(t["done_steps"], 1)

    def test_steps_all_success(self):
        t = {"id": "y", "novel": "n", "action": "generate", "args": [],
             "steps": [{"action": "generate", "args": ["1"]},
                       {"action": "generate", "args": ["2"]},
                       {"action": "summary", "args": ["1"]}],
             "status": "running", "lines": [], "done_steps": 0}
        T._TASKS["y"] = t
        calls = []
        real = T._run_step
        T._run_step = lambda task, cmd: (calls.append(cmd), 0)[1]
        try:
            T._worker("y")
        finally:
            T._run_step = real
        T._TASKS.pop("y", None)
        self.assertEqual(t["status"], "done")
        self.assertEqual(len(calls), 3)
        self.assertEqual(t["done_steps"], 3)
        joined = "".join(t["lines"])
        self.assertIn("步骤 3/3", joined)


if __name__ == "__main__":
    unittest.main()
