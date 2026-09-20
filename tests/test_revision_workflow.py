import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import engine.novel_creator as creator
import engine.settings as settings
from engine import pending
from engine.agents.archivist import ArchivistAgent
from engine.agents.dialogue_auditor import DialogueAuditor
from engine.agents.keeper import KeeperAgent
from engine.agents.planner import PlannerAgent
from engine.agents.story_keeper import StoryKeeperAgent, _empty_state
from engine.db import NovelDB
from engine.knowledge import check_ready, content_hash, rebuild, transaction
from engine.quality import edit_chapter, validate_verdict


class EditorialTests(unittest.TestCase):
    def test_only_false_quote_violations_can_be_filtered(self):
        auditor = DialogueAuditor.__new__(DialogueAuditor)
        for response, passed in (
            ({"passed": False, "violations": [{"issue": "格式", "fix": "改为直角引号"}]}, True),
            ({"passed": False, "violations": []}, False),
            ({}, False),
        ):
            with self.subTest(response=response), patch.object(auditor, "_build_prompt", return_value=""), \
                    patch.object(auditor, "_call_llm", return_value=response):
                self.assertEqual(auditor.audit("“走吧。”", {})["passed"], passed)

    def test_auditor_keeps_real_quotation_errors(self):
        auditor = DialogueAuditor.__new__(DialogueAuditor)
        response = {"passed": False, "violations": [{"issue": "格式", "fix": "补齐中文双引号"}]}
        for draft in ("「走吧。」", "“走吧。", "【走吧。】"):
            with self.subTest(draft=draft), patch.object(auditor, "_build_prompt", return_value=""), \
                    patch.object(auditor, "_call_llm", return_value=response):
                self.assertFalse(auditor.audit(draft, {})["passed"])

    def test_empty_and_contradictory_reviews_never_pass(self):
        for response in ({}, [], {"passed": True}, {"passed": "true", "errors": []},
                         {"passed": True, "errors": [{"type": "重复场景"}]}):
            self.assertFalse(validate_verdict(response)["passed"])

    def test_reader_objection_drives_repair_and_recheck(self):
        reviewer, reader, writer, auditor = Mock(), Mock(), Mock(), Mock()
        reviewer.chapter_check.return_value = {"passed": True, "errors": []}
        auditor.audit.return_value = {"passed": True, "violations": []}
        reader.read.side_effect = [{"overall_score": 5, "would_continue": False, "fatigue_points": ["脱困被写了两遍"]},
                                  {"overall_score": 8, "would_continue": True}]
        writer.apply_patches.return_value = "脱困后带走工钱，去修炉子。"
        with patch("engine.agents.story_keeper.story_check", return_value={"passed": True, "errors": []}):
            text, scan, result, history, passed = edit_chapter("脱困后又脱困。", {}, 1, {},
                SimpleNamespace(chapter_edit_max_retries=1), writer, reviewer, reader, auditor)
        self.assertTrue(passed)
        self.assertEqual(text, writer.apply_patches.return_value)
        self.assertEqual(reviewer.chapter_check.call_count, 2)
        self.assertEqual(reader.read.call_count, 2)
        self.assertIn("脱困被写了两遍", writer.apply_patches.call_args.args[2])
        self.assertEqual(len(history), 2)

    def test_unavailable_chapter_review_stays_pending(self):
        reviewer, reader, writer, auditor = Mock(), Mock(), Mock(), Mock()
        reviewer.chapter_check.return_value = {}
        auditor.audit.return_value = {"passed": True, "violations": []}
        reader.read.return_value = {"overall_score": 9, "would_continue": True}
        with patch("engine.agents.story_keeper.story_check", return_value={"passed": True, "errors": []}):
            *_, passed = edit_chapter("正文", {}, 1, {}, SimpleNamespace(), writer, reviewer, reader, auditor)
        self.assertFalse(passed)
        writer.apply_patches.assert_not_called()

    def test_scene_budgets_sum_to_chapter_budget(self):
        planner = PlannerAgent.__new__(PlannerAgent)
        planner.target_words = 3000
        plan = planner._validate_and_normalize({"scene_outline": [
            {"target_words": 2000}, {"target_words": 1000}, {"target_words": 1500}]}, 1)
        self.assertEqual(sum(scene["target_words"] for scene in plan["scene_outline"]), 3000)
        self.assertEqual([s["is_final_scene"] for s in plan["scene_outline"]], [False, False, True])

    def test_movement_is_not_an_immutable_contradiction(self):
        agent = StoryKeeperAgent()
        state = _empty_state()
        agent._merge_facts(state, 1, [{"entity": "沈渊", "attribute": "位置", "value": "工具舱"}])
        agent._merge_facts(state, 2, [{"entity": "沈渊", "attribute": "位置", "value": "巡检站"}])
        self.assertEqual(state["continuity_warnings"], [])
        self.assertEqual(state["facts"]["沈渊"]["位置"]["value"], "巡检站")

    def test_unresolved_questions_are_not_discarded_after_twelve(self):
        agent = StoryKeeperAgent()
        state = _empty_state()
        for chapter in range(1, 20):
            agent._merge_questions(state, chapter, [f"问题{chapter}"], [])
        self.assertEqual(len(state["open_questions"]), 19)
        self.assertEqual(state["open_questions"][0]["text"], "问题1")


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(patch.object(creator, "NOVELS_DIR", Path(directory)))
        self.stack.enter_context(patch.object(settings, "NOVELS_DIR", Path(directory)))
        self.stack.enter_context(patch.object(settings, "_config", None))
        self.stack.enter_context(patch.object(settings, "_current_novel", None))
        self.root = creator.create_novel("test", "验证", 4, 2500, "科幻", "资源回收")
        settings.set_novel("test")
        self.config = settings.get_config()
        self.stack.enter_context(patch("engine.llm_client.chat_json", side_effect=AssertionError("unexpected paid call")))

    def tearDown(self):
        from engine.prompts_loader import reload
        reload()
        self.stack.close()

    def record(self, text):
        return {"source_hash": content_hash(text), "plan": {"chapter_title": "新章"},
                "snapshot": {"plot_progress": text},
                "archive": {"chapter_summary": text, "character_updates": {"沈渊": {"location": "医院"}},
                            "facts": [{"subject": "沈渊", "content": text}], "confirmed_clue_operations": []},
                "story": {"facts": [{"entity": "沈渊", "attribute": "位置", "value": "医院"}],
                          "chapter_hooks": {"light_hook": "出院后修炉"}}}

    def test_rebuild_replaces_stale_state_from_final_manuscript(self):
        text = "沈渊去医院处理肩伤。"
        (self.config.generated_dir / "chapter_01.md").write_text(text, encoding="utf-8")
        (self.config.bible_dir / "story_state.json").write_text(json.dumps({"facts": {"旧地点": {}}}), encoding="utf-8")
        db = NovelDB(self.root)
        db.log_chapter(1, status="knowledge_stale")
        db.replace_chapter_derivatives(1, [], {}, "旧正文", "old")
        db.close()
        self.assertEqual(rebuild(self.config, records={"1": self.record(text)}), 1)
        state = json.loads((self.config.bible_dir / "story_state.json").read_text(encoding="utf-8"))
        self.assertNotIn("旧地点", state["facts"])
        self.assertEqual(state["facts"]["沈渊"]["位置"]["value"], "医院")
        db = NovelDB(self.root)
        try:
            self.assertEqual(db.recent_summaries(2)[0]["content_hash"], content_hash(text))
            self.assertEqual(db.conn.execute("SELECT status FROM chapter_log WHERE chapter=1").fetchone()[0], "generated")
        finally:
            db.close()
        check_ready(self.config, 2)

    def test_rebuild_failure_restores_all_derivatives_and_body(self):
        path = self.config.generated_dir / "chapter_01.md"
        path.write_text("旧正文", encoding="utf-8")
        old_chars = (self.config.bible_dir / "characters.json").read_bytes()
        db = NovelDB(self.root)
        db.replace_chapter_derivatives(1, [], {}, "旧摘要", "old")
        db.close()
        with patch.object(ArchivistAgent, "save_chapter", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                rebuild(self.config, replacement=(1, "新正文", {}), records={"1": self.record("新正文")})
        self.assertEqual(path.read_text(encoding="utf-8"), "旧正文")
        self.assertEqual((self.config.bible_dir / "characters.json").read_bytes(), old_chars)
        self.assertFalse((self.root / "knowledge_transaction.json").exists())
        db = NovelDB(self.root)
        try:
            self.assertEqual(db.recent_summaries(2)[0]["summary"], "旧摘要")
        finally:
            db.close()

    def test_pending_publish_recompresses_the_saved_revision(self):
        import novel
        pending.save_pending(self.config, 1, "改稿后在医院。", {
            "keeper_cache": {"current_chapter_snapshots": [{"plot_progress": "旧稿在家"}]}, "plan_json": {}})
        with patch.object(KeeperAgent, "_compress_scene", return_value={"plot_progress": "改稿后在医院"}) as compress, \
                patch.object(novel, "_publish_chapter") as publish:
            novel.cmd_publish(1)
        self.assertEqual(compress.call_args.args[0], "改稿后在医院。")
        cache = publish.call_args.args[4]
        self.assertEqual(cache["current_chapter_snapshots"][0]["plot_progress"], "改稿后在医院")

    def test_revise_runs_full_chapter_review_and_preserves_final_manuscript(self):
        import novel

        final_path = self.config.generated_dir / "chapter_01.md"
        final_path.write_text("旧定稿。", encoding="utf-8")
        plan = {"chapter_title": "旧章", "target_words": 2500, "scene_outline": []}
        (self.config.cache_dir / "archive_plan_01.json").write_text(
            json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        context = {
            "_plan": plan,
            "_story_state": {},
            "previous_chapter_tail": "前章结尾",
            "next_chapter_head": "后章开头",
            "relevant_characters": {"沈渊": {"voice": "少说废话"}},
        }
        scan = Mock()
        scan.passed = True
        scan.violations = []
        scan.warnings = []
        scan.metrics = {}
        scan.to_rows.return_value = []
        writer = Mock()
        writer._call_llm.return_value = "模型初稿。"
        reviews = [{"attempt": 1, "issues": [], "editorial": {"passed": True}}]

        with patch("novel._build_revision_context", return_value=context) as build_context, \
                patch("engine.agents.writer.WriterAgent", return_value=writer), \
                patch("engine.agents.reviewers.ReviewerAgent"), \
                patch("engine.agents.reader_proxy.ReaderProxy"), \
                patch("engine.agents.dialogue_auditor.DialogueAuditor"), \
                patch("engine.prompts_loader.get_prompt", return_value=("写作规则", "")), \
                patch("engine.quality.edit_chapter", return_value=(
                    "终审修订稿。", scan, {"overall_score": 8, "would_continue": True},
                    reviews, True,
                )) as edit:
            result = novel.cmd_revise(1, "修正时间线")

        self.assertEqual(result, 2)
        self.assertEqual(final_path.read_text(encoding="utf-8"), "旧定稿。")
        entry = pending.load_pending(self.config, 1)
        self.assertEqual(entry["content"], "终审修订稿。")
        self.assertTrue(entry["diagnostics"]["quality_passed"])
        self.assertEqual(entry["diagnostics"]["reader_result"]["overall_score"], 8)
        self.assertEqual(entry["diagnostics"]["reasons"]["chapter_review"], reviews)
        build_context.assert_called_once_with(
            self.config, 1, plan, "旧定稿。", "修正时间线")
        self.assertIs(edit.call_args.args[3], context)
        prompt = writer._call_llm.call_args.args[0]
        self.assertIn("前章结尾", prompt)
        self.assertIn("后章开头", prompt)

    def test_guards_missing_pending_and_stale_predecessors(self):
        with self.assertRaisesRegex(ValueError, "前置"):
            check_ready(self.config, 2)
        pending.save_pending(self.config, 1, "未定稿", {})
        with self.assertRaisesRegex(ValueError, "待修订"):
            check_ready(self.config, 2)
        pending.remove_pending(self.config, 1)
        (self.config.generated_dir / "chapter_01.md").write_text("定稿", encoding="utf-8")
        db = NovelDB(self.root)
        db.log_chapter(1, status="knowledge_stale")
        db.close()
        with self.assertRaisesRegex(ValueError, "知识已过期"):
            check_ready(self.config, 2)

    def test_body_version_mismatch_does_not_install_authored_records(self):
        (self.config.generated_dir / "chapter_01.md").write_text("新正文", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "版本不一致"):
            rebuild(self.config, records={"1": self.record("旧正文")})

    def test_direct_manuscript_edit_blocks_stale_knowledge(self):
        path = self.config.generated_dir / "chapter_01.md"
        path.write_text("原正文", encoding="utf-8")
        rebuild(self.config, records={"1": self.record("原正文")})
        path.write_text("手工改稿", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "知识已过期"):
            check_ready(self.config, 2)

    def test_publication_failure_preserves_pending_body(self):
        import novel
        pending.save_pending(self.config, 1, "待发布正文", {})
        with patch.object(novel, "_commit_chapter", side_effect=OSError("archive failed")):
            with self.assertRaisesRegex(OSError, "archive failed"):
                novel._publish_chapter(self.config, 1, "待发布正文", {}, {}, replacing=False)
        self.assertEqual((self.root / "revision/chapter_01.md").read_text(encoding="utf-8"), "待发布正文")
        self.assertFalse((self.config.generated_dir / "chapter_01.md").exists())

    def test_pending_is_removed_only_after_transaction_commits(self):
        import novel
        pending.save_pending(self.config, 1, "待发布正文", {})

        def committed(*args, **kwargs):
            self.assertTrue((self.root / "knowledge_transaction.json").exists())
            self.assertTrue((self.root / "revision/chapter_01.md").exists())

        with patch.object(novel, "_commit_chapter", side_effect=committed):
            novel._publish_chapter(self.config, 1, "待发布正文", {}, {}, replacing=False)
        self.assertFalse((self.root / "knowledge_transaction.json").exists())
        self.assertFalse((self.root / "revision/chapter_01.md").exists())

    def test_plan_only_foreshadowing_is_not_committed(self):
        agent = ArchivistAgent()
        self.assertTrue(agent.update_bible(1, {"clue_operations": [{"action": "plant", "clue_id": "F999"}]}, {}, "正文", extraction={
            "chapter_summary": "摘要", "confirmed_clue_operations": []}))
        db = NovelDB(self.root)
        try:
            self.assertIsNone(db.conn.execute("SELECT 1 FROM foreshadowing WHERE id='F999'").fetchone())
        finally:
            db.close()


class BatchRevisionTests(unittest.TestCase):
    def test_pending_exit_stops_following_steps(self):
        import server.tasks as tasks
        task = {"id": "pending-test", "novel": "test", "action": "generate", "args": [],
                "steps": [{"action": "generate", "args": ["1"]}, {"action": "generate", "args": ["2"]}],
                "status": "running", "lines": [], "done_steps": 0}
        with patch.dict(tasks._TASKS, {task["id"]: task}), patch.object(tasks, "_persist"), \
                patch.object(tasks, "_run_step", return_value=2) as run:
            tasks._worker(task["id"])
        self.assertEqual(task["status"], "needs_revision")
        self.assertEqual(task["done_steps"], 0)
        self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
