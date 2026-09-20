import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from engine.agents.archivist import ArchivistAgent
from engine.agents.keeper import KeeperAgent
from engine.agents.planner import PlannerAgent
from engine.agents.researcher import ResearcherAgent
from engine.db import NovelDB


class KeeperArchivistTests(unittest.TestCase):
    def test_carry_snapshots_are_not_sent_to_archivist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir = root / "cache"
            generated_dir = root / "generated"
            bible_dir = root / "bible"
            for directory in (cache_dir, generated_dir, bible_dir):
                directory.mkdir()
            (cache_dir / "keeper_cache_01.json").write_text(json.dumps({
                "chapter": 1,
                "snapshots": [{"scene_id": 1, "plot_progress": "前章秘密"}],
            }, ensure_ascii=False), encoding="utf-8")
            fake = SimpleNamespace(
                keeper_model=object(), archivist_model=object(), cache_dir=cache_dir,
                generated_dir=generated_dir, bible_dir=bible_dir,
            )
            with patch("engine.agents.keeper.config", fake):
                keeper = KeeperAgent()
                cache = keeper.init_cache(2)
                with patch("engine.prompts_loader.get_prompt", return_value=(
                    "{scene_draft}{scene_id}", ""
                )), patch.object(keeper, "_call_llm", return_value={
                    "plot_progress": "本章行动", "emotion_state": "紧张",
                    "env_and_clue": "仓库",
                }):
                    keeper.update(cache, "本章最终场景", 2, 1)
            captured = {}
            with patch("engine.agents.archivist.config", fake), patch(
                "engine.prompts_loader.get_prompt", return_value=("archive", "")
            ), patch(
                "engine.llm_client.chat_json",
                side_effect=lambda *args, **kwargs: captured.update(
                    json.loads(kwargs["user_prompt"])) or {
                        "character_updates": {}, "clue_updates": {}, "facts": [],
                        "chapter_summary": "本章摘要",
                        "confirmed_clue_operations": [],
                    },
            ), patch.object(ArchivistAgent, "_sync_db"):
                ok = ArchivistAgent().update_bible(2, {}, cache, "最终正文")
            self.assertTrue(ok)
            self.assertEqual(captured["full_chapter"], "最终正文")
            self.assertNotIn("前章秘密", json.dumps(captured, ensure_ascii=False))
            self.assertEqual(captured["current_chapter_snapshots"][0]["chapter_num"], 2)
            self.assertTrue(captured["current_chapter_snapshots"][0]["source_hash"])

    def test_invalidate_from_removes_current_and_future_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            fake = SimpleNamespace(keeper_model=object(), cache_dir=cache_dir)
            for chapter in (1, 2, 3):
                (cache_dir / f"keeper_cache_{chapter:02d}.json").write_text("{}")
            with patch("engine.agents.keeper.config", fake):
                removed = KeeperAgent().invalidate_from(2)
            self.assertEqual(removed, 2)
            self.assertTrue((cache_dir / "keeper_cache_01.json").exists())
            self.assertFalse((cache_dir / "keeper_cache_02.json").exists())


class SummaryReadTests(unittest.TestCase):
    def test_planner_and_researcher_prefer_database_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bible").mkdir()
            (root / "generated").mkdir()
            (root / "generated" / "chapter_01.md").write_text("正文首行", encoding="utf-8")
            db = NovelDB(root, auto_import=False)
            db.replace_chapter_derivatives(1, [], {}, "数据库摘要", "hash")
            db.close()
            fake = SimpleNamespace(bible_dir=root / "bible", generated_dir=root / "generated")
            with patch("engine.agents.planner.config", fake):
                planner_summary = PlannerAgent.__new__(PlannerAgent)._read_outline_summary(2)
            with patch("engine.agents.researcher.config", fake):
                researcher_summary = ResearcherAgent.__new__(ResearcherAgent)._read_recent_summaries(2)
            self.assertIn("数据库摘要", planner_summary)
            self.assertIn("数据库摘要", researcher_summary)
            self.assertNotIn("正文首行", planner_summary)


if __name__ == "__main__":
    unittest.main()
