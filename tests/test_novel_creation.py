import io
import json
import os
import tempfile
import zipfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import engine.novel_creator as novel_creator
import engine.settings as settings
import server.app as server_app
from engine import model_config


class TestNovelCreationAPI(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.novels_dir = Path(self._tmp.name) / "novels"
        self.novels_dir.mkdir()
        self._creator_dir = novel_creator.NOVELS_DIR
        self._server_dir = server_app.NOVELS_DIR
        self._settings_dir = settings.NOVELS_DIR
        self._model_config_dir = model_config.NOVELS_DIR
        self._current_novel = settings._current_novel
        self._config = settings._config
        novel_creator.NOVELS_DIR = self.novels_dir
        server_app.NOVELS_DIR = self.novels_dir
        settings.NOVELS_DIR = self.novels_dir
        model_config.NOVELS_DIR = self.novels_dir
        self.client = TestClient(server_app.app)

    def tearDown(self):
        novel_creator.NOVELS_DIR = self._creator_dir
        server_app.NOVELS_DIR = self._server_dir
        settings.NOVELS_DIR = self._settings_dir
        model_config.NOVELS_DIR = self._model_config_dir
        settings._current_novel = self._current_novel
        settings._config = self._config
        self._tmp.cleanup()

    def test_create_initializes_complete_workspace(self):
        response = self.client.post("/api/novels", json={
            "id": "small-book",
            "title": "小书",
            "chapter_count": 3,
            "words_per_chapter": 1200,
            "genre": "悬疑",
            "description": "测试简介",
        })
        self.assertEqual(response.status_code, 201, response.text)

        novel_dir = self.novels_dir / "small-book"
        self.assertTrue((novel_dir / ".env.example").is_file())
        self.assertFalse((novel_dir / ".env").exists())
        prompts = json.loads((novel_dir / "novel_prompts.json").read_text(encoding="utf-8"))
        for name in ("title_generator", "volume_summary", "planner", "writer"):
            self.assertIn(name, prompts)

        titles = self.client.get("/api/novels/small-book/titles").json()
        self.assertEqual(list(titles["volumes"]), ["volume_1"])
        self.assertEqual(
            list(self.client.get("/api/novels/small-book/bible").json()),
            server_app.BIBLE_FILES,
        )

    def test_config_reads_local_env_without_global_pollution(self):
        novel_creator.create_novel("configured-book", "配置测试", 1, 1000, "", "")
        novel_dir = self.novels_dir / "configured-book"
        (novel_dir / ".env").write_text(
            "API_KEY=local-key\nAPI_BASE_URL=https://local.example/v1\n"
            "PLANNER_MODEL=local-planner\nWRITER_MODEL=local-writer\n",
            encoding="utf-8",
        )
        with patch.dict(os.environ, {
            "API_KEY": "external-key", "API_BASE_URL": "https://external.example/v1",
            "PLANNER_MODEL": "external-planner",
        }, clear=False):
            config = settings.load_config("configured-book")
            self.assertEqual(os.environ["PLANNER_MODEL"], "external-planner")
        self.assertEqual(config.api_key, "local-key")
        self.assertEqual(config.base_url, "https://local.example/v1")
        self.assertEqual(config.planner_model.model_name, "local-planner")
        self.assertEqual(config.writer_model.model_name, "local-writer")

    def test_config_uses_root_env_when_local_is_absent_and_local_wins(self):
        (self.novels_dir.parent / ".env").write_text(
            "API_KEY=root-key\nAPI_BASE_URL=https://root.example/v1\n"
            "PLANNER_MODEL=root-planner\nWRITER_MODEL=root-writer\nTHEME_MODEL=root-theme\n",
            encoding="utf-8",
        )
        novel_creator.create_novel("global-book", "全局测试", 1, 1000, "", "")
        config = settings.load_config("global-book")
        self.assertEqual(config.api_key, "root-key")
        self.assertEqual(config.writer_model.model_name, "root-writer")
        view = model_config.get_view("global-book")
        self.assertEqual(view["theme_model"], "root-theme")
        self.assertEqual(view["roles"][-1]["model"], "deepseek-chat")
        (self.novels_dir / "global-book" / ".env").write_text(
            "WRITER_MODEL=local-writer\nTHEME_MODEL=local-theme\n", encoding="utf-8"
        )
        settings.invalidate_config("global-book")
        self.assertEqual(settings.load_config("global-book").writer_model.model_name, "local-writer")
        self.assertEqual(model_config.get_view("global-book")["theme_model"], "local-theme")

    def test_saved_env_invalidates_cached_config(self):
        novel_creator.create_novel(
            "cached-book", "缓存测试", 1, 1000, "", "",
            model_env={"WRITER_MODEL": "first-model"})
        settings.set_novel("cached-book")
        self.assertEqual(settings.get_config().writer_model.model_name, "first-model")
        model_config.save("cached-book", {"WRITER_MODEL": "second-model"})
        self.assertEqual(settings.get_config().writer_model.model_name, "second-model")

    def test_export_and_delete_are_safe(self):
        novel_creator.create_novel("archive-book", "归档测试", 1, 1000, "", "")
        d = self.novels_dir / "archive-book"
        (d / ".env").write_text("API_KEY=secret", encoding="utf-8")
        (d / "db").mkdir(exist_ok=True)
        (d / "db" / "private.sqlite").write_text("private", encoding="utf-8")
        response = self.client.get("/api/novels/archive-book/export")
        self.assertEqual(response.status_code, 200, response.text)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = set(archive.namelist())
        self.assertIn("config.py", names)
        self.assertIn("bible/master_bible.md", names)
        self.assertNotIn(".env", names)
        self.assertNotIn("db/private.sqlite", names)
        deleted = self.client.delete("/api/novels/archive-book")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(deleted.json(), {"ok": True, "id": "archive-book"})
        self.assertFalse(d.exists())

    def test_delete_rejects_running_task(self):
        novel_creator.create_novel("busy-book", "忙书", 1, 1000, "", "")
        with patch.object(server_app.T, "running_task", return_value="task-id"):
            response = self.client.delete("/api/novels/busy-book")
        self.assertEqual(response.status_code, 409)
        self.assertTrue((self.novels_dir / "busy-book").exists())

    def test_knowledge_base_fields_round_trip(self):
        created = self.client.post("/api/novels", json={
            "id": "crud-book", "title": "契约测试", "chapter_count": 8,
            "words_per_chapter": 1500,
        })
        self.assertEqual(created.status_code, 201, created.text)

        response = self.client.patch(
            "/api/novels/crud-book/db/characters/林一",
            json={
                "profile": {
                    "role": "主角", "voice_print": "短句",
                    "first_appearance_chapter": 2,
                },
                "chapter": 3,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        character = self.client.get("/api/novels/crud-book/db/characters").json()[0]
        self.assertEqual(character["first_appearance_chapter"], 2)
        self.assertEqual(character["updated_chapter"], 3)
        self.assertNotIn("profile_json", character)
        response = self.client.patch(
            "/api/novels/crud-book/db/characters/林一",
            json={"profile": {"role": "核心主角"}},
        )
        self.assertEqual(response.status_code, 200, response.text)
        character = self.client.get("/api/novels/crud-book/db/characters").json()[0]
        self.assertEqual(character["role"], "核心主角")
        self.assertEqual(character["voice_print"], "短句")
        characters_bible = json.loads((
            self.novels_dir / "crud-book" / "bible" / "characters.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(characters_bible["characters"]["林一"]["role"], "核心主角")

        response = self.client.patch(
            "/api/novels/crud-book/db/clues/C001",
            json={
                "name": "钥匙", "type": "物件", "description": "铜钥匙",
                "introduced_chapter": 2, "intended_reveal_chapter": 7,
                "resolved": False, "state": {"holder": "林一"}, "chapter": 3,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        clue = self.client.get("/api/novels/crud-book/db/clues").json()[0]
        self.assertEqual(clue["introduced_chapter"], 2)
        self.assertEqual(clue["intended_reveal_chapter"], 7)
        self.assertEqual(clue["updated_chapter"], 3)
        self.assertEqual(clue["state"], {"holder": "林一"})

        response = self.client.patch(
            "/api/novels/crud-book/db/foreshadowing/F001",
            json={
                "name": "钟声", "status": "active", "introduced_chapter": 1,
                "intended_payoff_chapter": 6, "description": "午夜钟声",
                "hinted_chapters": [1, 4],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        foreshadow = self.client.get(
            "/api/novels/crud-book/db/foreshadowing?current=5"
        ).json()
        self.assertEqual(foreshadow["rows"][0]["introduced_chapter"], 1)
        self.assertEqual(foreshadow["rows"][0]["hinted_chapters"], [1, 4])
        self.assertEqual(foreshadow["buckets"]["normal"][0]["hinted_chapters"], [1, 4])

        motif_content = json.dumps({
            "motifs": [{
                "id": "M001", "name": "雨", "description": "转折",
                "used_in_chapters": [2, 5],
            }]
        }, ensure_ascii=False)
        response = self.client.put(
            "/api/novels/crud-book/bible/motif_bank.json",
            json={"content": motif_content},
        )
        self.assertEqual(response.status_code, 200, response.text)
        motif = self.client.get("/api/novels/crud-book/db/motifs").json()[0]
        self.assertEqual(motif["used_in_chapters"], [2, 5])

    def test_dynamic_volumes_are_balanced_and_continuous(self):
        for chapters in (200, 500, 1000, 1500):
            volumes = novel_creator._volume_config(chapters)
            ranges = [value["chapters"] for value in volumes.values()]
            self.assertEqual(ranges[0][0], 1)
            self.assertEqual(ranges[-1][1], chapters)
            self.assertTrue(all(left[1] + 1 == right[0]
                                for left, right in zip(ranges, ranges[1:])))
            sizes = [hi - lo + 1 for lo, hi in ranges]
            self.assertTrue(all(40 <= size <= 80 for size in sizes))
            self.assertLessEqual(max(sizes) - min(sizes), 1)
        self.assertEqual(novel_creator._volume_config(3)["volume_1"]["chapters"], (1, 3))


class TestPromptsFactoryFallback(unittest.TestCase):
    """出厂模板兜底：老书的 novel_prompts.json 缺新 Agent 提示词时自动补齐，不覆盖定制内容。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.novels_dir = Path(self._tmp.name) / "novels"
        self.novels_dir.mkdir()
        self._settings_dir = settings.NOVELS_DIR
        settings.NOVELS_DIR = self.novels_dir
        self._current = settings._current_novel
        settings._current_novel = None
        import engine.prompts_loader as prompts_loader
        self.pl = prompts_loader
        prompts_loader.reload()

    def tearDown(self):
        settings.NOVELS_DIR = self._settings_dir
        settings._current_novel = self._current
        self.pl.reload()
        self._tmp.cleanup()

    def _make_old_novel(self):
        d = self.novels_dir / "old-book"
        d.mkdir()
        (d / "novel_prompts.json").write_text(json.dumps({
            "_meta": {"novel": "旧书", "genre": "都市", "description": "老书"},
            "writer": {"system": "CUSTOM_WRITER_SYSTEM", "chapter_template": ""},
        }, ensure_ascii=False), encoding="utf-8")
        (d / "config.py").write_text("# stub", encoding="utf-8")
        return d

    def test_missing_agent_prompts_filled_from_factory_without_overwriting(self):
        self._make_old_novel()
        settings.set_novel("old-book")
        # 老书没有 story_keeper / story_check → 出厂模板自动补齐
        system, _ = self.pl.get_prompt("story_keeper")
        self.assertIn("故事管理员", system)
        sys2, _ = self.pl.get_prompt("story_check")
        self.assertIn("故事逻辑审稿人", sys2)
        # 已定制的 writer 提示词不被覆盖
        wsys, _ = self.pl.get_prompt("writer")
        self.assertEqual(wsys, "CUSTOM_WRITER_SYSTEM")
        # 常规 key 不受影响
        self.assertTrue(self.pl.get_prompt("planner")[0])


if __name__ == "__main__":
    unittest.main()
