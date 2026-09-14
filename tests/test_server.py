# 后端 API 测试: python -m unittest tests.test_server -v
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

import engine.novel_creator as novel_creator
import engine.settings as settings
from engine.db import NovelDB
from engine.style_kit import scanner
import server.app as server_app


class TestServerAPI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.temp_root = Path(cls._tmp.name)
        cls.novels_dir = cls.temp_root / "novels"
        cls.novels_dir.mkdir()
        cls.style_dir = cls.temp_root / "style_kit"
        cls.style_dir.mkdir()
        shutil.copy(
            ROOT / "engine" / "style_kit" / "banned_words.json",
            cls.style_dir / "banned_words.json",
        )

        cls._original_rules_file = scanner.RULES_FILE
        cls._patches = [
            patch.object(settings, "NOVELS_DIR", cls.novels_dir),
            patch.object(novel_creator, "NOVELS_DIR", cls.novels_dir),
            patch.object(server_app, "NOVELS_DIR", cls.novels_dir),
            patch.object(server_app, "SK", cls.style_dir),
        ]
        for item in cls._patches:
            item.start()
        scanner.RULES_FILE = cls.style_dir / "banned_words.json"

        novel_creator.create_novel(
            "my-story", "我的小说", 8, 1500, "悬疑", "临时服务端测试小说"
        )
        novel_dir = cls.novels_dir / "my-story"
        (novel_dir / "generated" / "chapter_01.md").write_text(
            "「门外是谁？」\n林一握紧钥匙，没敢开门。", encoding="utf-8"
        )
        (novel_dir / "generated" / "chapter_02.md").write_text(
            '然而门开了。\n他说："别动。"', encoding="utf-8"
        )
        db = NovelDB(novel_dir)
        try:
            db.upsert_character(
                "林一",
                {
                    "role": "主角",
                    "voice_print": "短句",
                    "first_appearance_chapter": 1,
                },
                1,
            )
            db.upsert_foreshadow(
                "F001",
                {
                    "name": "旧钥匙",
                    "status": "active",
                    "introduced_chapter": 1,
                    "intended_payoff_chapter": 6,
                    "description": "钥匙来源不明",
                    "hinted_chapters": [1],
                },
            )
        finally:
            db.close()

        cls.c = TestClient(server_app.app)

    @classmethod
    def tearDownClass(cls):
        server_app.T._TASKS.clear()
        server_app.T._LOCKS.clear()
        scanner.RULES_FILE = cls._original_rules_file
        for item in reversed(cls._patches):
            item.stop()
        cls._tmp.cleanup()

    def test_01_novels_list(self):
        response = self.c.get("/api/novels")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([novel["id"] for novel in response.json()], ["my-story"])

    def test_02_status(self):
        response = self.c.get("/api/novels/my-story/status")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["title"], "我的小说")
        self.assertEqual(data["written"], 2)
        self.assertIn("volumes", data)
        self.assertIn("db", data)

    def test_03_chapters(self):
        rows = self.c.get("/api/novels/my-story/chapters").json()
        self.assertEqual([row["num"] for row in rows], [1, 2])
        response = self.c.get("/api/novels/my-story/chapters/1")
        self.assertIn("握紧钥匙", response.json()["content"])

    def test_04_scan(self):
        response = self.c.get("/api/novels/my-story/scan/2")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertIn("metrics", data)
        self.assertFalse(data["passed"])
        self.assertTrue(data["metrics"]["has_halfwidth_quote"])

    def test_05_db_browse(self):
        characters = self.c.get("/api/novels/my-story/db/characters").json()
        self.assertEqual(characters[0]["name"], "林一")
        foreshadow = self.c.get(
            "/api/novels/my-story/db/foreshadowing?current=5"
        ).json()
        self.assertEqual(foreshadow["rows"][0]["id"], "F001")
        style_hits = self.c.get("/api/novels/my-story/db/style-hits").json()
        self.assertIn("patterns", style_hits)

    def test_06_style_kit_roundtrip_uses_temporary_copy(self):
        response = self.c.get("/api/style-kit")
        data = response.json()
        self.assertIn("hard_words", data)
        saved = self.c.put("/api/style-kit", json=data)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertTrue(saved.json()["ok"])
        self.assertEqual(scanner.RULES_FILE.parent, self.style_dir)

    def test_07_chapter_save_revalidates(self):
        content = self.c.get("/api/novels/my-story/chapters/1").json()["content"]
        response = self.c.put(
            "/api/novels/my-story/chapters/1", json={"content": content}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("scan", response.json())

    def test_08_task_submission_and_event_stream(self):
        with patch.object(server_app.T, "running_task", return_value=None), patch.object(
            server_app.T, "submit", return_value="temporary-task"
        ) as submit:
            response = self.c.post("/api/novels/my-story/tasks/db", json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["task_id"], "temporary-task")
        submit.assert_called_once_with("my-story", "db", ["init"])

        server_app.T._TASKS["temporary-task"] = {
            "id": "temporary-task",
            "novel": "my-story",
            "action": "db",
            "args": ["init"],
            "status": "done",
            "lines": ["知识库已导入\n"],
            "started": 0,
        }
        got = []
        with self.c.stream("GET", "/api/tasks/temporary-task/events") as stream:
            for line in stream.iter_lines():
                if line.startswith("data:"):
                    got.append(json.loads(line[5:].strip()))
        self.assertEqual(got, ["知识库已导入\n", "__TASK_END__ done"])

    def test_09_task_lock(self):
        with patch.object(server_app.T, "running_task", return_value="busy-task"), patch.object(
            server_app.T, "submit"
        ) as submit:
            response = self.c.post("/api/novels/my-story/tasks/db", json={})
        self.assertEqual(response.status_code, 409)
        submit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
