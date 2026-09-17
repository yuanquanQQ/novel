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
from engine.agents.foreshadowing_steward import ForeshadowingSteward
from engine.agents.keeper import KeeperAgent
from engine.agents.planner import PlannerAgent
from engine.agents.reader_proxy import ReaderProxy
from engine.agents.researcher import ResearcherAgent
from engine.agents.reviewers import ReviewerAgent
from engine.agents.story_keeper import (
    StoryKeeperAgent, _empty_state, append_volume_revisions, planner_context,
    record_actual_events, story_check, writer_warnings,
)
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

    def _patches(self, drafts, scans, reviews, audits, story_checks=None):
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
            StoryKeeperAgent,
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
            patch.object(StoryKeeperAgent, "load_state", return_value=_empty_state()),
            patch.object(StoryKeeperAgent, "update_state", return_value=_empty_state()),
        ])
        # 故事逻辑闸门：默认全程放行；传入 side_effect 可测“故事逻辑不过→重试”
        if story_checks is None:
            patches.append(patch(
                "engine.agents.story_keeper.story_check",
                return_value={"passed": True, "errors": [], "suggestions": ""},
            ))
        else:
            patches.append(patch(
                "engine.agents.story_keeper.story_check",
                side_effect=story_checks,
            ))
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

    def test_exhaustion_accepts_best_draft_and_publishes(self):
        failed = ScanResult(violations=[{
            "category": "禁用词", "pattern": "坏", "count": 1,
            "where": "全文", "hint": "删",
        }])
        passed = ScanResult()
        patches = self._patches(
            ["失败一", "失败二"], [failed, failed, passed],
            [{"passed": True}, {"passed": True}],
            [{"passed": True}, {"passed": True}],
        )
        with ExitStack() as stack:
            for item in patches:
                stack.enter_context(item)
            novel.cmd_generate(1)
        # 闸门重试耗尽不再整章失败：接受最佳稿继续发布，诊断留存 failed_drafts 供事后审阅
        self.assertTrue((self.config.generated_dir / "chapter_01.md").exists())
        failed_file = self.config.cache_dir / "failed_drafts" / "chapter_01_scene_1.md"
        self.assertEqual(failed_file.read_text(encoding="utf-8"), "失败二")
        self.assertTrue(failed_file.with_suffix(".json").exists())

    def test_gate_retries_when_story_logic_fails(self):
        # 风格/语义/声纹全过，但故事逻辑闸门第一轮判违规（事实矛盾）→ 携建议重试，二轮通过
        passed = ScanResult()
        story_fail = {
            "passed": False,
            "errors": [{"type": "事实矛盾", "paragraph": "他在星港", "suggestion": "补过渡"}],
            "suggestions": "事实矛盾：角色位置与前文冲突，补充转移过渡。",
        }
        story_ok = {"passed": True, "errors": [], "suggestions": ""}
        patches = self._patches(
            ["矛盾稿", "修订稿"], [passed, passed, passed],
            [{"passed": True}, {"passed": True}],
            [{"passed": True}, {"passed": True}],
            story_checks=[story_fail, story_ok],
        )
        with ExitStack() as stack:
            for item in patches:
                stack.enter_context(item)
            novel.cmd_generate(1)
        # 二轮通过 → 正文是修订稿
        self.assertEqual(
            (self.config.generated_dir / "chapter_01.md").read_text(encoding="utf-8"),
            "修订稿",
        )

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
    def test_invalid_operations_dropped_with_warnings_not_raising(self):
        """未知伏笔引用与重复 plant 只丢弃并记警告，不再中断整章生成。"""
        steward = ForeshadowingSteward.__new__(ForeshadowingSteward)
        bible = {"clues": {"active_foreshadowing": {"F001": {}}}}
        with patch.object(steward, "_build_prompt", return_value="prompt"), \
                patch.object(steward, "_call_llm", return_value={}) as call:
            plan = {"clue_operations": [
                {"clue_id": "F404", "action": "reveal"},
                {"clue_id": "F001", "action": "plant"},
                {"clue_id": "F001", "action": "hint", "method": "再次出现"},
            ]}
            result = steward.audit(plan, 3, bible)
        self.assertEqual(call.call_count, 1)
        # F404 reveal 指向未知伏笔、F001 重复 plant 都被丢弃；合法 hint 保留
        self.assertEqual(plan["clue_operations"], [
            {"clue_id": "F001", "action": "hint", "method": "再次出现"},
        ])
        self.assertEqual(len(result["operation_warnings"]), 2)

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

    def test_planner_retries_with_contract_feedback_then_recovers(self):
        """plant 缺 name/description 时重试，重试提示须携带伏笔操作契约。"""
        planner = PlannerAgent.__new__(PlannerAgent)
        broken = {"clue_operations": [{"clue_id": "F100", "action": "plant"}]}
        good = {"clue_operations": [{
            "clue_id": "F101", "action": "plant", "name": "空盒",
            "description": "盒底有划痕", "method": "桌上",
        }]}
        prompts = []

        def fake_llm(prompt):
            prompts.append(prompt)
            return broken if len(prompts) == 1 else good

        with patch.object(planner, "_build_prompt", return_value="BASE"), patch.object(
                planner, "_call_llm", side_effect=fake_llm):
            plan = planner.run(2, "继续", {}, [])
        self.assertEqual(len(prompts), 2)
        self.assertIn("【伏笔操作契约】", prompts[1])
        self.assertIn("plant F100 必须包含 name 和 description", prompts[1])
        self.assertEqual(plan["clue_operations"][0]["clue_id"], "F101")
        self.assertEqual(plan["clue_operations"][0]["introduced_chapter"], 2)

    def test_planner_exhaustion_falls_back_to_lenient_and_survives(self):
        """连续失败后降级宽容模式，丢弃非法伏笔操作而不整章崩溃。"""
        planner = PlannerAgent.__new__(PlannerAgent)
        broken = {"scene_outline": [{}],
                  "clue_operations": [{"clue_id": "F100", "action": "plant"}]}
        with patch.object(planner, "_build_prompt", return_value="BASE"), patch.object(
                planner, "_call_llm", return_value=broken) as llm:
            plan = planner.run(3, "继续", {}, [])
        self.assertEqual(llm.call_count, 3)
        self.assertEqual(plan["clue_operations"], [])
        self.assertIn("scene_outline", plan)

    def test_planner_retries_when_hint_targets_unknown_clue(self):
        """hint 指向线索网络中不存在的编号时重试，重试提示须携带该错误。"""
        planner = PlannerAgent.__new__(PlannerAgent)
        bible = {"clues": {"active_foreshadowing": {"F001": {}}}}
        bad = {"clue_operations": [{"clue_id": "F002", "action": "hint", "method": "桌上"}]}
        good = {"clue_operations": [{"clue_id": "F001", "action": "hint", "method": "桌上"}]}
        prompts = []

        def fake_llm(prompt):
            prompts.append(prompt)
            return bad if len(prompts) == 1 else good

        with patch.object(planner, "_build_prompt", return_value="BASE"), patch.object(
                planner, "_call_llm", side_effect=fake_llm):
            plan = planner.run(1, "继续", bible, [])
        self.assertEqual(len(prompts), 2)
        self.assertIn("F002 指向未知伏笔", prompts[1])
        self.assertEqual(plan["clue_operations"][0]["clue_id"], "F001")

    def test_planner_lenient_drops_hint_to_unknown_clue_when_bible_empty(self):
        """线索网络为空时，模型虚构 hint 编号连续失败后宽容丢弃，正文照常生成。"""
        planner = PlannerAgent.__new__(PlannerAgent)
        bible = {"clues": {"active_foreshadowing": {}}}
        bad = {"scene_outline": [{}],
               "clue_operations": [{"clue_id": "F002", "action": "hint", "method": "桌上"}]}
        with patch.object(planner, "_build_prompt", return_value="BASE"), patch.object(
                planner, "_call_llm", return_value=bad) as llm:
            plan = planner.run(1, "继续", bible, [])
        self.assertEqual(llm.call_count, 3)
        self.assertEqual(plan["clue_operations"], [])
        self.assertIn("scene_outline", plan)

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


class TestStoryKeeper(unittest.TestCase):
    """StoryKeeper：故事状态、连续性对账、问题台账、承诺同步、卷修订闭环。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bible = self.root / "bible"
        self.bible.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _agent(self):
        sk = StoryKeeperAgent()
        # __init__ 的 model_config 只影响真实 LLM 抽取；确定性测试不需要
        sk.model_config = None
        return sk

    def test_fact_contradiction_detection_major_and_minor(self):
        sk = self._agent()
        state = _empty_state()
        sk._merge_facts(state, 1, [
            {"entity": "沈渊", "attribute": "位置", "value": "零号废墟"},
            {"entity": "沈渊", "attribute": "习惯", "value": "常去一号车间"},
        ])
        sk._merge_facts(state, 2, [
            {"entity": "沈渊", "attribute": "位置", "value": "星港码头"},
            {"entity": "沈渊", "attribute": "习惯", "value": "常去三号仓库"},
        ])
        self.assertEqual(len(state["continuity_warnings"]), 2)
        by_attr = {w["attribute"]: w for w in state["continuity_warnings"]}
        self.assertEqual(by_attr["位置"]["severity"], "major")
        self.assertEqual(by_attr["习惯"]["severity"], "minor")
        self.assertEqual(by_attr["位置"]["prior"], "零号废墟")
        self.assertEqual(by_attr["位置"]["now"], "星港码头")
        # 同一值重复出现不产生新警告
        sk._merge_facts(state, 3, [
            {"entity": "沈渊", "attribute": "位置", "value": "星港码头"},
        ])
        self.assertEqual(len(state["continuity_warnings"]), 2)

    def test_questions_add_and_resolve(self):
        sk = self._agent()
        state = _empty_state()
        sk._merge_questions(state, 5, ["奇点吞噬体为何认主"], [])
        sk._merge_questions(state, 6, ["联邦舰队何时到"], ["Q00501"])
        ids = [q["id"] for q in state["open_questions"]]
        # id = Q{章}{全局递增序号}：第二个问题序号按当前台账长度递增
        self.assertEqual(ids, ["Q00501", "Q00602"])
        self.assertEqual(state["open_questions"][0]["status"], "resolved")
        self.assertEqual(state["open_questions"][0]["resolved_chapter"], 6)
        self.assertEqual(state["open_questions"][1]["status"], "open")

    def test_sync_promises_from_clues(self):
        sk = self._agent()
        clues = {
            "active_foreshadowing": {
                "F001": {"name": "奇点吞噬体", "status": "pending",
                         "introduced_chapter": 1, "last_hinted_chapter": 3},
                "F002": {"name": "联邦密探", "status": "resolved",
                         "introduced_chapter": 2},
                "F003": {"name": "泰坦信标", "status": "escalated",
                         "introduced_chapter": 5},
            }
        }
        (self.bible / "clues.json").write_text(
            json.dumps(clues), encoding="utf-8")
        state = _empty_state()
        sk._sync_promises(state, self.bible)
        self.assertEqual(set(state["unresolved_promises"]), {"F001", "F003"})
        self.assertEqual(state["unresolved_promises"]["F001"]["name"], "奇点吞噬体")
        self.assertEqual(state["unresolved_promises"]["F001"]["planted_chapter"], 1)

    def test_planner_context_lists_promises_questions_arcs(self):
        state = {
            "unresolved_promises": {
                "F001": {"name": "奇点吞噬体", "planted_chapter": 1, "status": "pending"},
            },
            "open_questions": [
                {"id": "Q00501", "text": "联邦舰队何时到", "status": "open"},
            ],
            "character_arcs": {
                "沈渊": {"goal": "建立庇护所", "fear": "暴露", "secret": "", "conflict": "",
                         "change": "获得星核", "last_chapter": 3},
            },
            "continuity_warnings": [
                {"chapter": 2, "entity": "沈渊", "attribute": "位置",
                 "prior": "零号废墟", "now": "星港码头", "severity": "major"},
            ],
            "hook_log": [],
        }
        text = planner_context(state, 4)
        self.assertIn("奇点吞噬体", text)
        self.assertIn("联邦舰队何时到", text)
        self.assertIn("建立庇护所", text)
        self.assertIn("星港码头", text)

    def test_writer_warnings_includes_previous_hook(self):
        state = {
            "unresolved_promises": {},
            "open_questions": [
                {"id": "Q00301", "text": "空港里的女人是谁", "status": "open"},
            ],
            "continuity_warnings": [],
            "hook_log": [
                {"chapter": 3, "light": "窗外亮起红色警报", "dark": "",
                 "carried_into": 4},
            ],
        }
        text = writer_warnings(state, 4)
        self.assertIn("空港里的女人是谁", text)
        self.assertIn("窗外亮起红色警报", text)
        # 钩子只对下一章生效：第 5 章不再要求响应第 3 章钩子
        self.assertNotIn("窗外亮起红色警报", writer_warnings(state, 5))

    def test_update_state_roundtrip_with_synced_promises(self):
        sk = self._agent()
        (self.bible / "clues.json").write_text(json.dumps({
            "active_foreshadowing": {
                "F001": {"name": "奇点吞噬体", "status": "pending",
                         "introduced_chapter": 1},
            }
        }), encoding="utf-8")
        plan = {"chapter_title": "第一章", "chapter_hooks": {
            "light_hook": "门被推开", "dark_hook": ""}}
        with patch.object(sk, "_extract", return_value={
            "facts": [{"entity": "沈渊", "attribute": "位置", "value": "零号废墟"}],
            "arc_updates": [{"character": "沈渊", "goal": "活下去"}],
            "new_questions": ["废墟里还有什么"],
            "resolved_question_ids": [],
        }):
            state = sk.update_state(self.bible, 1, plan, {}, "正文")
        self.assertEqual(state["last_updated"], 1)
        self.assertEqual(state["facts"]["沈渊"]["位置"]["value"], "零号废墟")
        self.assertEqual(state["character_arcs"]["沈渊"]["goal"], "活下去")
        self.assertEqual(state["unresolved_promises"]["F001"]["name"], "奇点吞噬体")
        # 落盘后可读回
        reloaded = sk.load_state(self.bible)
        self.assertEqual(reloaded["facts"]["沈渊"]["位置"]["value"], "零号废墟")
        self.assertEqual(reloaded["hook_log"][0]["light"], "门被推开")
        # 坏 clues.json 不炸
        (self.bible / "clues.json").write_text("{bad json", encoding="utf-8")
        state2 = sk.update_state(self.bible, 2, plan, {}, "正文")
        self.assertEqual(state2["unresolved_promises"], {})

    def test_record_actual_events_appends_and_dedupes(self):
        sk_config = SimpleNamespace(bible_dir=self.bible)
        fake = SimpleNamespace(close=lambda: None)
        fake.conn = SimpleNamespace(execute=lambda *_: SimpleNamespace(fetchone=lambda: {"summary": "沈渊启动奇点炉"}))
        with patch("engine.settings.get_novel_dir", return_value=self.root), \
             patch("engine.db.NovelDB", return_value=fake):
            entry = record_actual_events(sk_config, 1, {"chapter_title": "废铁场"}, {})
        self.assertIn("第1章", entry)
        fp = self.bible / "actual_timeline.md"
        self.assertIn("沈渊启动奇点炉", fp.read_text(encoding="utf-8"))
        # 同章重写原位替换，不产生重复条目
        fake2 = SimpleNamespace(close=lambda: None)
        fake2.conn = SimpleNamespace(execute=lambda *_: SimpleNamespace(fetchone=lambda: {"summary": "改写版摘要"}))
        with patch("engine.settings.get_novel_dir", return_value=self.root), \
             patch("engine.db.NovelDB", return_value=fake2):
            record_actual_events(sk_config, 1, {"chapter_title": "废铁场"}, {})
        text = fp.read_text(encoding="utf-8")
        self.assertEqual(text.count("- 第1章"), 1)
        self.assertIn("改写版摘要", text)
        # DB 不可用 → 仍写占位，不抛异常
        with patch("engine.db.NovelDB", side_effect=RuntimeError("no novel")), \
             patch("engine.settings.get_novel_dir", side_effect=RuntimeError("no novel")):
            record_actual_events(sk_config, 2, {"chapter_title": "第二章"}, {})
        self.assertIn("第2章", fp.read_text(encoding="utf-8"))

    def test_story_check_passes_on_valid_draft_and_builds_prompt(self):
        state = {
            "facts": {"沈渊": {"位置": {"value": "零号废墟", "chapters": [1]}}},
            "open_questions": [{"id": "Q00201", "text": "奇点炉为何认主", "status": "open"}],
            "unresolved_promises": {"F001": {"name": "联邦密探", "status": "pending"}},
            "continuity_warnings": [],
            "hook_log": [{"chapter": 2, "light": "红色警报亮起", "dark": "", "carried_into": 3}],
        }
        calls = {}
        def fake_chat(mc, **kw):
            calls["prompt"] = kw["user_prompt"]
            return {"passed": True, "errors": [], "suggestions": ""}
        with patch("engine.agents.story_keeper.config",
                   SimpleNamespace(story_keeper_model=object(), writer_model=object())), \
             patch("engine.prompts_loader.get_prompt", return_value=("sys {facts} {open_questions} {promises} {hook} {draft}", "")), \
             patch("engine.llm_client.chat_json", side_effect=fake_chat):
            result = story_check(state, 3, {"scene_id": 1}, "沈渊修理零件", {})
        self.assertTrue(result["passed"])
        p = calls["prompt"]
        self.assertIn("零号废墟", p)
        self.assertIn("奇点炉为何认主", p)
        self.assertIn("联邦密探", p)
        self.assertIn("红色警报亮起", p)
        self.assertIn("沈渊修理零件", p)
        # 草稿与前文事实矛盾 → 模型判违规，闸门不通过
        with patch("engine.agents.story_keeper.config",
                   SimpleNamespace(story_keeper_model=object(), writer_model=object())), \
             patch("engine.prompts_loader.get_prompt", return_value=("sys", "")), \
             patch("engine.llm_client.chat_json", return_value={
                 "passed": False,
                 "errors": [{"type": "事实矛盾", "paragraph": "沈渊在星港", "suggestion": "补过渡"}],
                 "suggestions": "位置矛盾，补充转移过渡。",
             }):
            bad = story_check(state, 3, {"scene_id": 1}, "沈渊在星港码头谈生意", {})
        self.assertFalse(bad["passed"])
        self.assertEqual(bad["errors"][0]["type"], "事实矛盾")

    def test_story_check_fails_open_on_any_error(self):
        # 无小说上下文（get_prompt 抛错）→ 放行，绝不阻断
        with patch("engine.prompts_loader.get_prompt", side_effect=RuntimeError("未设置小说")):
            result = story_check({}, 1, {"scene_id": 1}, "草稿", {})
        self.assertTrue(result["passed"])
        self.assertEqual(result["errors"], [])

    def test_append_volume_revisions_writes_and_returns_block(self):
        sk_config = SimpleNamespace(
            bible_dir=self.bible,
            writer_model=None,
            story_keeper_model=None,
            volume_config={
                "volume_1": {"name": "第1卷", "chapters": (1, 60)},
                "volume_2": {"name": "第2卷", "chapters": (61, 120)},
            },
        )
        with patch("engine.llm_client.chat", return_value="- 加快第2卷冲突节奏\n- 回收 F001"):
            block = append_volume_revisions(sk_config, 1, "第1卷总结……")
        self.assertIn("第1卷", block)
        rev = (self.bible / "volume_revisions.md").read_text(encoding="utf-8")
        self.assertIn("回收 F001", rev)
        # 无卷配置 → 跳过
        with patch("engine.llm_client.chat", return_value="x"):
            self.assertEqual(append_volume_revisions(
                SimpleNamespace(bible_dir=self.bible, volume_config={}), 9, "总结"), "")


if __name__ == "__main__":
    unittest.main()
