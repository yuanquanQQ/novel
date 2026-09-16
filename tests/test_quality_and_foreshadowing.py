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

    def test_archivist_failure_does_not_publish_staged_chapter(self):
        passed = ScanResult()
        patches = self._patches(
            ["场景正文"], [passed, passed], [{"passed": True}], [{"passed": True}],
        )
        with ExitStack() as stack:
            for item in patches:
                stack.enter_context(item)
            stack.enter_context(patch.object(ArchivistAgent, "update_bible", return_value=False))
            with self.assertRaisesRegex(RuntimeError, "正文未发布"):
                novel.cmd_generate(1)
        self.assertFalse((self.config.generated_dir / "chapter_01.md").exists())

    def test_existing_chapter_requires_explicit_overwrite(self):
        self.config.generated_dir.mkdir()
        chapter = self.config.generated_dir / "chapter_01.md"
        chapter.write_text("旧正文", encoding="utf-8")
        patches = self._patches([], [], [], [])
        with ExitStack() as stack:
            for item in patches:
                stack.enter_context(item)
            with self.assertRaisesRegex(FileExistsError, "--overwrite"):
                novel.cmd_generate(1)
        self.assertEqual(chapter.read_text(encoding="utf-8"), "旧正文")

    def test_overwrite_marks_following_knowledge_stale(self):
        self.config.generated_dir.mkdir()
        chapter = self.config.generated_dir / "chapter_01.md"
        chapter.write_text("旧正文", encoding="utf-8")
        db = NovelDB(self.root)
        db.log_chapter(2, words=20)
        db.replace_chapter_derivatives(2, [], {}, "旧摘要", "old-hash")
        db.close()
        passed = ScanResult()
        patches = self._patches(
            ["新正文"], [passed, passed], [{"passed": True}], [{"passed": True}],
        )
        invalidated = []
        with ExitStack() as stack:
            for item in patches:
                stack.enter_context(item)
            stack.enter_context(patch.object(
                KeeperAgent, "invalidate_from",
                side_effect=lambda chapter_num: invalidated.append(chapter_num),
            ))
            novel.cmd_generate(1, overwrite=True)
        self.assertEqual(chapter.read_text(encoding="utf-8"), "新正文")
        self.assertEqual(invalidated, [2])
        db = NovelDB(self.root)
        try:
            self.assertEqual(db.conn.execute(
                "SELECT status FROM chapter_log WHERE chapter=2"
            ).fetchone()[0], "knowledge_stale")
            self.assertIsNone(db.conn.execute(
                "SELECT 1 FROM chapter_summaries WHERE chapter=2"
            ).fetchone())
        finally:
            db.close()

    def test_heavy_patch_is_reviewed_again_and_reconciles_snapshot(self):
        self.config.heavy_review_interval = 1
        passed = ScanResult()
        patches = self._patches(
            ["原正文"], [passed, passed, passed],
            [{"passed": True}], [{"passed": True}],
        )
        captured = {}

        def reconcile(_self, cache, text, chapter):
            cache["all_scenes"] = [text]
            cache["current_chapter_snapshots"] = [{
                "chapter_num": chapter, "scene_id": "final", "source_hash": text,
            }]
            return cache

        def archive(_self, chapter, _plan, cache, text):
            captured.update(chapter=chapter, cache=cache, text=text)
            return True

        with ExitStack() as stack:
            for item in patches:
                stack.enter_context(item)
            heavy = stack.enter_context(patch.object(
                ReviewerAgent, "heavy_check", side_effect=[
                    {"score": 7, "patch_instructions": ["修正"]},
                    {"score": 9, "patch_instructions": []},
                ],
            ))
            stack.enter_context(patch.object(
                WriterAgent, "apply_patches", return_value="修订正文",
            ))
            stack.enter_context(patch.object(
                KeeperAgent, "reconcile_final_chapter", new=reconcile,
            ))
            stack.enter_context(patch.object(
                ArchivistAgent, "update_bible", new=archive,
            ))
            novel.cmd_generate(1)
        self.assertEqual(heavy.call_count, 2)
        self.assertEqual(captured["text"], "修订正文")
        self.assertEqual(
            captured["cache"]["current_chapter_snapshots"][0]["source_hash"],
            "修订正文",
        )


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

    def test_archivist_file_failure_rolls_back_json_and_database(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            bible_dir = root / "bible"
            bible_dir.mkdir()
            characters_file = bible_dir / "characters.json"
            clues_file = bible_dir / "clues.json"
            characters_file.write_text(
                json.dumps({"characters": {"林一": {"role": "主角"}}}),
                encoding="utf-8",
            )
            clues_file.write_text(
                json.dumps({"clues": {}, "active_foreshadowing": {}}),
                encoding="utf-8",
            )
            before_characters = characters_file.read_text(encoding="utf-8")
            before_clues = clues_file.read_text(encoding="utf-8")
            archivist = ArchivistAgent.__new__(ArchivistAgent)
            archivist.model_config = object()
            archivist.bible_dir = bible_dir
            archivist._db = lambda: NovelDB(root)
            real_write = archivist._atomic_write
            calls = 0

            def fail_second(path, content):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected write failure")
                return real_write(path, content)

            extracted = {
                "chapter_summary": "摘要",
                "character_updates": {"林一": {"location": "车站"}},
                "clue_updates": {"C1": {"status": "new"}},
                "facts": [{"kind": "plot", "subject": "林一", "content": "抵达"}],
            }
            with patch("engine.llm_client.chat_json", return_value=extracted), patch(
                "engine.prompts_loader.get_prompt", return_value=("system", {})
            ), patch.object(archivist, "_atomic_write", side_effect=fail_second):
                ok = archivist.update_bible(
                    1, {"chapter_title": "抵达", "clue_operations": []},
                    {"current_chapter_snapshots": [], "_style_hits": []}, "正文",
                )
            self.assertFalse(ok)
            self.assertEqual(characters_file.read_text(encoding="utf-8"), before_characters)
            self.assertEqual(clues_file.read_text(encoding="utf-8"), before_clues)
            db = NovelDB(root)
            try:
                self.assertIsNone(db.conn.execute(
                    "SELECT 1 FROM chapter_summaries WHERE chapter=1"
                ).fetchone())
                self.assertEqual(db.conn.execute(
                    "SELECT COUNT(*) FROM chapter_facts WHERE chapter=1"
                ).fetchone()[0], 0)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
