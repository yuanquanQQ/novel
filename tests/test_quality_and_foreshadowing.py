import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import novel
from engine.agents.archivist import ArchivistAgent
from engine.agents.dialogue_auditor import DialogueAuditor
from engine.agents.foreshadowing_steward import (
    ForeshadowingProtocolError,
    ForeshadowingSteward,
)
from engine.agents.keeper import KeeperAgent
from engine.agents.planner import PlannerAgent
from engine.agents.reader_proxy import ReaderProxy
from engine.agents.researcher import ResearcherAgent
from engine.agents.reviewers import ReviewerAgent
from engine.agents.writer import WriterAgent
from engine.db import NovelDB
from engine.style_kit.scanner import ScanResult


class TestSceneQualityGate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.config = SimpleNamespace(
            story_title="测试书", bible_dir=self.root / "bible",
            generated_dir=self.root / "generated", cache_dir=self.root / "cache",
            immediate_review_max_retries=1, heavy_review_interval=99,
        )
        self.saved_cache = None

    def tearDown(self):
        self._tmp.cleanup()

    def _patches(self, drafts, scans, reviews, audits):
        plan = {
            "chapter_title": "测试章",
            "scene_outline": [{"scene_id": 1, "type": "breathable"}],
            "clue_operations": [],
        }

        def keeper_update(_self, cache, draft, chapter, scene):
            result = dict(cache)
            result.setdefault("all_scenes", []).append(draft)
            result.setdefault("current_chapter_snapshots", []).append({
                "chapter_num": chapter, "scene_id": scene,
            })
            return result

        def save_chapter(_self, chapter, text):
            self.config.generated_dir.mkdir(parents=True, exist_ok=True)
            (self.config.generated_dir / f"chapter_{chapter:02d}.md").write_text(
                text, encoding="utf-8"
            )

        def save_cache(_self, _chapter, cache):
            self.saved_cache = cache

        constructors = [
            PlannerAgent, ResearcherAgent, WriterAgent, ReviewerAgent, KeeperAgent,
            ArchivistAgent, DialogueAuditor, ForeshadowingSteward, ReaderProxy,
        ]
        patches = [patch.object(cls, "__init__", return_value=None) for cls in constructors]
        patches.extend([
            patch.object(novel, "get_config", return_value=self.config),
            patch.object(novel, "get_novel_dir", return_value=self.root),
            patch.object(PlannerAgent, "run", return_value=plan),
            patch.object(ForeshadowingSteward, "audit", return_value={}),
            patch.object(ResearcherAgent, "run", return_value={}),
            patch.object(KeeperAgent, "init_cache", return_value={"all_scenes": []}),
            patch.object(KeeperAgent, "update", new=keeper_update),
            patch.object(KeeperAgent, "save_cache", new=save_cache),
            patch.object(WriterAgent, "run", side_effect=drafts),
            patch.object(WriterAgent, "merge_scenes", side_effect=lambda scenes, *_: "\n".join(scenes)),
            patch.object(ReviewerAgent, "immediate_check", side_effect=reviews),
            patch.object(DialogueAuditor, "audit", side_effect=audits),
            patch.object(ArchivistAgent, "save_chapter", new=save_chapter),
            patch.object(ArchivistAgent, "update_bible", return_value=True),
            patch.object(ReaderProxy, "read", return_value={
                "overall_score": 8, "would_continue": True,
            }),
            patch("engine.style_kit.scanner.scan", side_effect=scans),
        ])
        return patches

    def test_gate_accepts_only_when_all_three_pass_and_styles_are_final_only(self):
        bad = ScanResult(violations=[{
            "category": "禁用词", "pattern": "坏", "count": 1,
            "where": "全文", "hint": "删",
        }])
        final = ScanResult(warnings=[{
            "category": "节奏", "pattern": "最终", "count": 2,
            "where": "全文", "hint": "调",
        }])
        patches = self._patches(
            ["失败草稿", "最终正文"], [bad, final, final],
            [{"passed": True}, {"passed": True}],
            [{"passed": True}, {"passed": True}],
        )
        with ExitStack() as stack:
            for item in patches:
                stack.enter_context(item)
            novel.cmd_generate(1)
        self.assertEqual(
            (self.config.generated_dir / "chapter_01.md").read_text(encoding="utf-8"),
            "最终正文",
        )
        self.assertEqual(self.saved_cache["_style_hits"], [
            (1, "节奏", "最终", 2),
        ])

    def test_exhaustion_does_not_publish_and_saves_failed_draft(self):
        failed = ScanResult(violations=[{
            "category": "禁用词", "pattern": "坏", "count": 1,
            "where": "全文", "hint": "删",
        }])
        patches = self._patches(
            ["失败一", "失败二"], [failed, failed],
            [{"passed": True}, {"passed": True}],
            [{"passed": True}, {"passed": True}],
        )
        for item in patches:
            item.start()
        try:
            with self.assertRaises(novel.SceneQualityError):
                novel.cmd_generate(1)
        finally:
            for item in reversed(patches):
                item.stop()
        self.assertFalse((self.config.generated_dir / "chapter_01.md").exists())
        failed_file = self.config.cache_dir / "failed_drafts" / "chapter_01_scene_1.md"
        self.assertEqual(failed_file.read_text(encoding="utf-8"), "失败二")
        self.assertTrue(failed_file.with_suffix(".json").exists())

    def test_merged_chapter_failure_does_not_publish(self):
        passed = ScanResult()
        failed = ScanResult(violations=[{
            "category": "排版", "pattern": "合并违规", "count": 1,
            "where": "全文", "hint": "修复",
        }])
        patches = self._patches(
            ["场景正文"], [passed, failed], [{"passed": True}], [{"passed": True}],
        )
        with ExitStack() as stack:
            for item in patches:
                stack.enter_context(item)
            with self.assertRaises(novel.SceneQualityError):
                novel.cmd_generate(1)
        self.assertFalse((self.config.generated_dir / "chapter_01.md").exists())
        failed_file = self.config.cache_dir / "failed_drafts" / "chapter_01_scene_merged.md"
        self.assertEqual(failed_file.read_text(encoding="utf-8"), "场景正文")


class TestForeshadowProtocol(unittest.TestCase):
    def test_unknown_and_duplicate_plant_block_before_llm(self):
        steward = ForeshadowingSteward.__new__(ForeshadowingSteward)
        bible = {"clues": {"active_foreshadowing": {"F001": {}}}}
        with patch.object(steward, "_call_llm") as call:
            with self.assertRaises(ForeshadowingProtocolError):
                steward.audit({"clue_operations": [
                    {"clue_id": "F404", "action": "reveal"}
                ]}, 3, bible)
            with self.assertRaises(ForeshadowingProtocolError):
                steward.audit({"clue_operations": [
                    {"clue_id": "F001", "action": "plant"}
                ]}, 3, bible)
            call.assert_not_called()

    def test_stale_reminder_uses_individual_interval(self):
        steward = ForeshadowingSteward.__new__(ForeshadowingSteward)
        bible = {"clues": {"active_foreshadowing": {
            "F001": {
                "status": "pending", "introduced_chapter": 5,
                "touch_interval": 3,
            }
        }}}
        with patch.object(steward, "_build_prompt", return_value="prompt"), \
                patch.object(steward, "_call_llm", return_value={}):
            result = steward.audit({"clue_operations": []}, 9, bible)
        self.assertEqual(result["stale"], ["F001"])
        self.assertIn("长期未触碰: F001", result["reminders"])

    def test_planner_normalizes_and_validates_operations(self):
        planner = PlannerAgent.__new__(PlannerAgent)
        plan = planner._validate_and_normalize({
            "scene_outline": [{}],
            "clue_operations": [{
                "id": "F100", "action": "PLANT", "name": "空盒",
                "description": "盒底有划痕",
            }],
        }, 4)
        self.assertEqual(plan["clue_operations"][0]["action"], "plant")
        self.assertEqual(plan["clue_operations"][0]["clue_id"], "F100")
        self.assertEqual(plan["clue_operations"][0]["introduced_chapter"], 4)

    def test_archivist_plant_hint_reveal_keeps_json_and_db_aligned(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            bible_dir = root / "bible"
            bible_dir.mkdir()
            clues_file = bible_dir / "clues.json"
            clues_file.write_text(json.dumps({
                "clues": {}, "active_foreshadowing": {}
            }), encoding="utf-8")
            archivist = ArchivistAgent.__new__(ArchivistAgent)
            archivist.bible_dir = bible_dir
            archivist._db = lambda: NovelDB(root)
            ops = [
                {"clue_id": "F100", "action": "plant", "name": "空盒",
                 "description": "盒底有划痕", "touch_interval": 6},
                {"clue_id": "F100", "action": "hint", "method": "再次出现"},
                {"clue_id": "F100", "action": "reveal", "method": "打开盒底"},
            ]
            for chapter, op in enumerate(ops, 1):
                archivist._sync_db(chapter, {}, {"chapter_summary": "摘要"}, [op], "正文")
                archivist._update_foreshadowing(chapter, {"clue_operations": [op]})
            data = json.loads(clues_file.read_text(encoding="utf-8"))
            self.assertEqual(data["active_foreshadowing"]["F100"]["status"], "resolved")
            self.assertEqual(data["active_foreshadowing"]["F100"]["hinted_chapters"], [1, 2])
            db = NovelDB(root)
            try:
                row = db.conn.execute(
                    "SELECT * FROM foreshadowing WHERE id='F100'"
                ).fetchone()
                self.assertEqual(row["status"], "resolved")
                self.assertEqual(row["resolved_ch"], 3)
                self.assertEqual(json.loads(row["hinted_chs"]), [1, 2])
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
