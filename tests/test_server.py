# 后端 API 测试: python -m unittest tests.test_server -v
import io
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
import zipfile
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

    def test_07_chapter_save_revalidates_and_marks_knowledge_stale(self):
        book = self.novels_dir / "my-story"
        db = NovelDB(book)
        db.replace_chapter_derivatives(1, [{
            "kind": "plot", "subject": "旧", "content": "旧事实"
        }], {"林一": {"location": "门口"}}, "旧摘要", "old-hash")
        db.close()
        for chapter in (1, 2):
            (book / "cache" / f"keeper_cache_{chapter:02d}.json").write_text("{}")
        content = self.c.get("/api/novels/my-story/chapters/1").json()["content"]
        response = self.c.put(
            "/api/novels/my-story/chapters/1", json={"content": content}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["knowledge_stale"])
        rows = self.c.get("/api/novels/my-story/chapters").json()
        self.assertTrue(rows[0]["knowledge_stale"])
        db = NovelDB(book)
        self.assertEqual(db.conn.execute(
            "SELECT COUNT(*) FROM chapter_summaries WHERE chapter=1").fetchone()[0], 0)
        db.close()
        self.assertFalse((book / "cache" / "keeper_cache_01.json").exists())
        self.assertFalse((book / "cache" / "keeper_cache_02.json").exists())

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

    def test_10_cancel_task_endpoint(self):
        with patch.object(server_app.T, "cancel", return_value={
                "id": "running-task", "status": "cancelled", "cancelled": True}):
            response = self.c.post("/api/tasks/running-task/cancel")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "cancelled")
        with patch.object(server_app.T, "cancel", return_value=None):
            response = self.c.post("/api/tasks/missing/cancel")
        self.assertEqual(response.status_code, 404)

    def test_11_workspace_backup_and_restore(self):
        book = self.novels_dir / "my-story"
        (book / ".env").write_text("API_KEY=secret", encoding="utf-8")
        (book / "cache" / "keeper_cache_01.json").write_text("{}", encoding="utf-8")
        (book / "cache" / "failed_drafts").mkdir(exist_ok=True)
        (book / "cache" / "failed_drafts" / "bad.md").write_text("bad", encoding="utf-8")
        (book / "bible" / "outline_manifest.json").write_text('{"parts": []}', encoding="utf-8")
        (book / "bible" / "outline_parts" / "volume_1").mkdir(parents=True, exist_ok=True)
        (book / "bible" / "outline_parts" / "volume_1" / "section_1_8.md").write_text("part", encoding="utf-8")
        response = self.c.get("/api/novels/my-story/backup")
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.content
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            names = set(zf.namelist())
            self.assertIn("config.py", names)
            self.assertIn("novel_prompts.json", names)
            self.assertIn("db/novel.db", names)
            self.assertIn("cache/keeper_cache_01.json", names)
            self.assertIn("bible/outline_manifest.json", names)
            self.assertIn("bible/outline_parts/volume_1/section_1_8.md", names)
            self.assertFalse(any(".env" in Path(name).parts for name in names))
            self.assertFalse(any("failed_drafts" in name for name in names))
            db_bytes = zf.read("db/novel.db")
        snapshot = self.temp_root / "snapshot.db"
        snapshot.write_bytes(db_bytes)
        conn = sqlite3.connect(str(snapshot))
        self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        conn.close()

        restored = self.c.post(
            "/api/novels/import-backup?id=restored-story",
            content=payload, headers={"content-type": "application/zip"})
        self.assertEqual(restored.status_code, 201, restored.text)
        restored_dir = self.novels_dir / "restored-story"
        self.assertTrue((restored_dir / "generated" / "chapter_01.md").exists())
        self.assertTrue((restored_dir / "db" / "novel.db").exists())
        self.assertFalse((restored_dir / ".env").exists())
        duplicate = self.c.post("/api/novels/import-backup?id=restored-story", content=payload)
        self.assertEqual(duplicate.status_code, 409)
        shutil.rmtree(restored_dir)

    def test_12_backup_import_rejects_zip_slip_and_limits(self):
        required = {
            "config.py": "config = None",
            "novel_prompts.json": "{}",
            "bible/master_bible.md": "# test",
        }
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            for name, content in required.items():
                zf.writestr(name, content)
            zf.writestr("../escape.txt", "bad")
        response = self.c.post("/api/novels/import-backup?id=bad-slip", content=archive.getvalue())
        self.assertEqual(response.status_code, 400)
        self.assertFalse((self.novels_dir / "bad-slip").exists())

        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            for name, content in required.items():
                zf.writestr(name, content)
            zf.writestr(".env", "API_KEY=secret")
        response = self.c.post("/api/novels/import-backup?id=bad-env", content=archive.getvalue())
        self.assertEqual(response.status_code, 400)

        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            for name, content in required.items():
                zf.writestr(name, content)
            zf.writestr("cache/large.bin", "x" * 20)
        with patch.object(server_app, "MAX_BACKUP_FILE_BYTES", 10):
            response = self.c.post("/api/novels/import-backup?id=too-large", content=archive.getvalue())
        self.assertEqual(response.status_code, 413)

    def test_13_chapter_pagination_filters_and_boundaries(self):
        response = self.c.get("/api/novels/my-story/chapters-page?offset=0&limit=1")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["total"], 2)
        self.assertEqual([item["num"] for item in data["items"]], [1])
        response = self.c.get("/api/novels/my-story/chapters-page?offset=1&limit=1&q=2")
        self.assertEqual(response.json(), {"items": [], "total": 1})
        response = self.c.get("/api/novels/my-story/chapters-page?status=knowledge_stale")
        self.assertEqual([item["num"] for item in response.json()["items"]], [1])
        response = self.c.get("/api/novels/my-story/chapters-page?chapter_from=2&chapter_to=2")
        self.assertEqual([item["num"] for item in response.json()["items"]], [2])
        self.assertEqual(self.c.get("/api/novels/my-story/chapters-page?limit=201").status_code, 422)
        self.assertEqual(self.c.get("/api/novels/my-story/chapters-page?chapter_from=3&chapter_to=2").status_code, 422)

    def test_14_novel_list_prefers_complete_db_word_totals(self):
        book = self.novels_dir / "my-story"
        db = NovelDB(book, auto_import=False)
        db.conn.execute(
            "INSERT OR REPLACE INTO chapter_log(chapter, words, status) VALUES(1, 123, 'generated')")
        db.conn.execute(
            "INSERT OR REPLACE INTO chapter_log(chapter, words, status) VALUES(2, 456, 'generated')")
        db.conn.commit()
        db.close()
        original_read_text = Path.read_text
        def guarded_read_text(path, *args, **kwargs):
            if path.parent.name == "generated":
                raise AssertionError("不应读取正文")
            return original_read_text(path, *args, **kwargs)
        with patch.object(Path, "read_text", guarded_read_text):
            response = self.c.get("/api/novels")
        self.assertEqual(response.status_code, 200, response.text)
        row = next(item for item in response.json() if item["id"] == "my-story")
        self.assertEqual(row["words"], 579)


if __name__ == "__main__":
    unittest.main()
