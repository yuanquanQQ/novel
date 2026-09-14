# 后端 API 冒烟测试: python -m unittest tests.test_server -v
import json
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from server.app import app


class TestServerAPI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.c = TestClient(app)

    def test_01_novels_list(self):
        r = self.c.get("/api/novels")
        self.assertEqual(r.status_code, 200)
        ids = [n["id"] for n in r.json()]
        self.assertIn("mirror-city", ids)

    def test_02_status(self):
        r = self.c.get("/api/novels/mirror-city/status")
        d = r.json()
        self.assertEqual(d["title"], "镜影迷城")
        self.assertIn("volumes", d)
        self.assertIn("db", d)

    def test_03_chapters(self):
        r = self.c.get("/api/novels/mirror-city/chapters")
        rows = r.json()
        self.assertTrue(rows)
        n = rows[0]["num"]
        r2 = self.c.get(f"/api/novels/mirror-city/chapters/{n}")
        self.assertIn("content", r2.json())

    def test_04_scan(self):
        r = self.c.get("/api/novels/mirror-city/scan/2")
        d = r.json()
        self.assertIn("metrics", d)
        self.assertFalse(d["passed"])   # 旧章节应有违规（回归基线）

    def test_05_db_browse(self):
        r = self.c.get("/api/novels/mirror-city/db/characters")
        self.assertTrue(r.json())
        r = self.c.get("/api/novels/mirror-city/db/foreshadowing?current=50")
        self.assertIn("buckets", r.json())
        r = self.c.get("/api/novels/mirror-city/db/style-hits")
        self.assertIn("patterns", r.json())

    def test_06_style_kit_roundtrip(self):
        r = self.c.get("/api/style-kit")
        data = r.json()
        self.assertIn("hard_words", data)
        r2 = self.c.put("/api/style-kit", json=data)   # 原样保存
        self.assertTrue(r2.json()["ok"])

    def test_07_chapter_save_revalidates(self):
        text = (self.c.get("/api/novels/mirror-city/chapters/1")
                .json()["content"])
        r = self.c.put("/api/novels/mirror-city/chapters/1",
                       json={"content": text})          # 原样回存
        self.assertEqual(r.status_code, 200)
        self.assertIn("scan", r.json())

    def test_08_task_db_init_streams(self):
        r = self.c.post("/api/novels/mirror-city/tasks/db", json={})
        self.assertEqual(r.status_code, 200, r.text)
        tid = r.json()["task_id"]
        got = []
        with self.c.stream("GET", f"/api/tasks/{tid}/events") as s:
            for line in s.iter_lines():
                if line.startswith("data:"):
                    payload = json.loads(line[5:].strip())
                    got.append(payload)
                    if "__TASK_END__" in payload:
                        break
                if len(got) > 50:
                    break
        self.assertTrue(any("知识库" in g or "characters=" in g for g in got))
        self.assertTrue(got[-1].startswith("__TASK_END__ done"), got[-1])

    def test_09_task_lock(self):
        r1 = self.c.post("/api/novels/wangu-changqing/tasks/db", json={})
        self.assertEqual(r1.status_code, 200)
        r2 = self.c.post("/api/novels/wangu-changqing/tasks/db", json={})
        # 可能 409（还在跑）或 200（已完成）——不该 500
        self.assertIn(r2.status_code, (200, 409))
        if r2.status_code == 200:
            tid = r2.json()["task_id"]
            with self.c.stream("GET", f"/api/tasks/{tid}/events") as s:
                for line in s.iter_lines():
                    if "__TASK_END__" in line:
                        break


if __name__ == "__main__":
    unittest.main()
