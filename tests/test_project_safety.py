from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
import engine.novel_creator as creator
import engine.settings as settings
from engine.authoring import record_edit, apply_edits
from engine import checkpoint
from engine.knowledge import content_hash, ensure_seed, rebuild, transaction
from engine.locking import novel_lock, NovelBusyError
from engine.memory import select_memory
from engine.usage import CallBudgetExceeded, reserve_call, usage_run, task_limit

ROOT = Path(__file__).resolve().parents[1]


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.books = Path(directory) / "novels"
        for module in (creator, settings):
            self.stack.enter_context(patch.object(module, "NOVELS_DIR", self.books))
        self.stack.enter_context(patch.object(settings, "_config", None))
        self.stack.enter_context(patch.object(settings, "_current_novel", None))
        import server.app as app
        self.stack.enter_context(patch.object(app, "NOVELS_DIR", self.books))
        self.stack.enter_context(patch("engine.llm_client.chat_json", side_effect=AssertionError("paid call forbidden")))
        self.root = creator.create_novel("project-test", "测试", 10, 2500, "悬疑", "追查旧案")
        settings.set_novel("project-test")
        self.config = settings.get_config()
        self.client = TestClient(app.app)

    def tearDown(self):
        from engine.prompts_loader import reload
        reload()
        self.stack.close()

    def install_record(self, chapter=1):
        text = f"第{chapter}章正文。"
        (self.config.generated_dir / f"chapter_{chapter:02d}.md").write_text(text, encoding="utf-8")
        return {"source_hash": content_hash(text), "plan": {}, "snapshot": {"plot_progress": text},
                "archive": {"chapter_summary": text, "character_updates": {"主角": {"goal": "模型乱改", "location": "现场"}},
                            "confirmed_clue_operations": []},
                "story": {"facts": [{"entity": "主角", "attribute": "位置", "value": "现场"}]}}

    def profiles(self):
        return json.loads((self.config.bible_dir / "characters.json").read_text(encoding="utf-8"))

    def seed_profile(self):
        data = {"characters": {"主角": {"goal": "旧目标", "voice_print": "少言", "location": "家中"}}}
        (self.config.bible_dir / "characters.json").write_text(json.dumps(data), encoding="utf-8")
        ensure_seed(self.config)
        return data

    def test_api_author_profile_survives_rebuild_and_model_extraction(self):
        self.seed_profile()
        record = self.install_record()
        response = self.client.patch("/api/novels/project-test/db/characters/主角",
                                     json={"profile": {"goal": "查明真相", "location": "医院"}, "chapter": 1})
        self.assertEqual(response.status_code, 200, response.text)
        rebuild(self.config, records={"1": record})
        self.assertEqual(self.profiles()["characters"]["主角"]["goal"], "查明真相")
        self.assertEqual(self.profiles()["characters"]["主角"]["location"], "医院")
        state = json.loads((self.config.bible_dir / "story_state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["facts"]["主角"]["位置"]["value"], "医院")
        from engine.db import NovelDB
        db = NovelDB(self.root)
        try:
            profile = json.loads(db.conn.execute("SELECT profile_json FROM characters WHERE name='主角'").fetchone()[0])
            self.assertEqual(profile["goal"], "查明真相")
            self.assertEqual(profile["location"], "医院")
            history = json.loads(db.conn.execute(
                "SELECT state_json FROM character_states WHERE character='主角' AND chapter=1").fetchone()[0])
            self.assertEqual(history["location"], "医院")
        finally:
            db.close()

    def test_direct_stable_author_edit_survives_rebuild(self):
        data = self.seed_profile()
        data["characters"]["主角"]["goal"] = "作者手改"
        (self.config.bible_dir / "characters.json").write_text(json.dumps(data), encoding="utf-8")
        rebuild(self.config, records={"1": self.install_record()})
        self.assertEqual(self.profiles()["characters"]["主角"]["goal"], "作者手改")

    def test_initial_runtime_edit_can_evolve_after_first_chapter(self):
        old = self.seed_profile()
        new = json.loads(json.dumps(old))
        new["characters"]["主角"]["location"] = "车站"
        record_edit(self.root, "characters.json", old, new, chapter=0)
        rebuild(self.config, records={"1": self.install_record()})
        self.assertEqual(self.profiles()["characters"]["主角"]["location"], "现场")

    def test_deleted_character_is_not_resurrected_by_stable_overrides(self):
        old = self.seed_profile()
        revised = json.loads(json.dumps(old))
        revised["characters"]["主角"]["goal"] = "查案"
        record_edit(self.root, "characters.json", old, revised, chapter=1)
        record_edit(self.root, "characters.json", revised, {"characters": {}}, chapter=2)
        apply_edits(self.root, 3)
        self.assertNotIn("主角", self.profiles()["characters"])

    def test_checkpoint_inputs_invalidate_on_author_or_model_changes(self):
        def current():
            return checkpoint.checkpoint_path(self.config, 1, "继续", "开篇")
        first = current()
        self.assertEqual(first, current())
        self.config.base_url += "/other"
        self.assertNotEqual(first, current())
        second = current()
        self.config.reader_proxy_model.temperature += 0.1
        self.assertNotEqual(second, current())
        third = current()
        (self.config.bible_dir / "master_bible.md").write_text("作者的新设定", encoding="utf-8")
        self.assertNotEqual(third, current())
        fourth = current()
        (self.config.cache_dir / "keeper_cache_00.json").write_text("{}", encoding="utf-8")
        self.assertNotEqual(fourth, current())

    def test_checkpoint_rejects_inconsistent_progress(self):
        path = self.config.cache_dir / "invalid.json"
        checkpoint.save(path, {"scene_outline": [{"scene_id": 1}]}, {"all_scenes": []}, 1, [])
        with self.assertRaises(ValueError):
            checkpoint.load(path)

    def test_snapshots_share_only_backup_files_and_rollback(self):
        self.seed_profile()
        source = self.config.bible_dir / "characters.json"
        original = source.read_bytes()
        with transaction(self.root) as first:
            pass
        with transaction(self.root) as second:
            pass
        a, b = first / "bible/characters.json", second / "bible/characters.json"
        self.assertTrue(os.path.samefile(a, b))
        self.assertFalse(os.path.samefile(source, b))
        with patch("engine.knowledge.os.link", side_effect=OSError("unsupported")):
            with self.assertRaisesRegex(RuntimeError, "abort"):
                with transaction(self.root) as third:
                    source.write_text("{}", encoding="utf-8")
                    raise RuntimeError("abort")
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(a.read_bytes(), original)
        self.assertFalse(os.path.samefile(a, third / "bible/characters.json"))

    def test_raw_bible_edits_are_recorded_and_replayed(self):
        data = self.seed_profile()
        record = self.install_record()
        data["characters"]["主角"].update(goal="原始文件编辑", location="车站")
        response = self.client.put("/api/novels/project-test/bible/characters.json",
                                   json={"content": json.dumps(data, ensure_ascii=False)})
        self.assertEqual(response.status_code, 200, response.text)
        rebuild(self.config, records={"1": record})
        self.assertEqual(self.profiles()["characters"]["主角"]["location"], "车站")

    def test_new_clue_and_payoff_plan_survive_rebuild(self):
        ensure_seed(self.config)
        record = self.install_record()
        response = self.client.patch("/api/novels/project-test/db/foreshadowing/F901",
                                     json={"name": "作者伏笔", "intended_payoff_chapter": 8})
        self.assertEqual(response.status_code, 200, response.text)
        rebuild(self.config, records={"1": record})
        clues = json.loads((self.config.bible_dir / "clues.json").read_text(encoding="utf-8"))
        self.assertEqual(clues["active_foreshadowing"]["F901"]["intended_payoff_chapter"], 8)

    def test_override_write_failure_rolls_back_author_edit(self):
        old = self.seed_profile()
        with patch("engine.authoring.record_edit", side_effect=OSError("disk full")):
            from server.app import _patch_db_and_bible
            with self.assertRaises(OSError):
                _patch_db_and_bible(self.root, "character", "主角", {"profile": {"goal": "新目标"}})
        self.assertEqual(self.profiles(), old)

    def test_shared_rules_apply_to_existing_custom_prompts_without_overwrite(self):
        from engine import prompts_loader
        path = self.root / "novel_prompts.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["writer"]["system"] = "作者自定义文风"
        path.write_text(json.dumps(data), encoding="utf-8")
        prompts_loader.reload()
        prompt, _ = prompts_loader.get_prompt("writer")
        self.assertIn("作者自定义文风", prompt)
        self.assertIn("项目级连载创作与编辑契约", prompt)
        self.assertIn("对手与反制", prompt)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), data)

    def test_cli_rejects_busy_book_before_dispatch(self):
        import novel
        with patch.object(novel, "_parse_args", return_value={"command": "status", "novel": "project-test"}), \
                patch("engine.locking.novel_lock", side_effect=NovelBusyError("busy")), patch.object(novel, "_dispatch") as dispatch:
            self.assertEqual(novel.main(), 1)
            dispatch.assert_not_called()

    def test_cli_create_obeys_the_shared_lock(self):
        import novel
        with patch("engine.locking.novel_lock", side_effect=NovelBusyError("busy")), \
                patch.object(creator, "create_novel") as create:
            with self.assertRaises(NovelBusyError):
                novel.cmd_create({"id": "new-book"})
            create.assert_not_called()

    def test_lock_directory_never_appears_as_a_book(self):
        import novel
        with novel_lock(self.root):
            pass
        response = self.client.get("/api/novels")
        self.assertEqual([book["id"] for book in response.json()], ["project-test"])
        output = io.StringIO()
        with patch.object(novel, "NOVELS_DIR", self.books), redirect_stdout(output):
            novel.cmd_list()
        self.assertNotIn(".locks", output.getvalue())


class LockTests(unittest.TestCase):
    def contender(self, root):
        code = "from pathlib import Path\nfrom engine.locking import novel_lock, NovelBusyError\nimport sys\ntry:\n with novel_lock(Path(sys.argv[1])): print('acquired')\nexcept NovelBusyError:\n print('busy')\n"
        result = subprocess.run([sys.executable, "-c", code, str(root)], cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_process_contention_reentrancy_and_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "book"
            root.mkdir()
            with novel_lock(root), novel_lock(root):
                self.assertEqual(self.contender(root), "busy")
                self.assertEqual(self.contender(root.parent / "other"), "acquired")
            self.assertEqual(self.contender(root), "acquired")

    def test_crashed_owner_does_not_leave_stale_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "book"
            code = "from engine.locking import novel_lock\nimport sys, time\nwith novel_lock(sys.argv[1]):\n print('ready', flush=True)\n time.sleep(30)\n"
            proc = subprocess.Popen([sys.executable, "-c", code, str(root)], cwd=ROOT,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(proc.stdout.readline().strip(), "ready")
                proc.kill()
                proc.communicate(timeout=10)
                self.assertEqual(self.contender(root), "acquired")
            finally:
                if proc.poll() is None:
                    proc.kill()
                proc.communicate(timeout=10)


class MemoryTests(unittest.TestCase):
    def test_relevant_entity_and_late_attribute_are_selected(self):
        facts = {f"person{i}": {f"attr{j}": {"value": "值", "chapters": [1]} for j in range(8)} for i in range(50)}
        result = select_memory({"facts": facts}, 2, {"entities": {"characters": ["person49"]}}, fact_limit=12)
        self.assertIn("attr7", result["facts"]["person49"])
        self.assertEqual(sum(map(len, result["facts"].values())), 12)

    def test_old_questions_and_due_promises_are_not_starved(self):
        state = {"open_questions": [{"id": f"Q{i}", "text": f"疑问{i}", "status": "open", "raised_chapter": i}
                                    for i in range(1, 20)],
                 "unresolved_promises": {f"F{i}": {"name": f"伏笔{i}", "planted_chapter": i,
                     "intended_payoff_chapter": 20 if i == 1 else 100} for i in range(1, 20)}}
        selected = select_memory(state, 21, issue_limit=4)
        self.assertEqual(selected["open_questions"][0]["id"], "Q1")
        self.assertIn("F1", selected["unresolved_promises"])
        self.assertEqual(len(state["open_questions"]), 19)


class UsageTests(unittest.TestCase):
    def test_bulk_default_scales_and_explicit_budget_always_wins(self):
        config = SimpleNamespace(chapter_count=600)
        self.assertEqual(task_limit(config, "generate"), 120)
        self.assertEqual(task_limit(config, "outline"), 7200)
        with tempfile.TemporaryDirectory() as directory:
            config.generated_dir = Path(directory)
            for chapter in range(1, 21):
                (config.generated_dir / f"chapter_{chapter:02d}.md").touch()
            self.assertEqual(task_limit(config, "rebuild"), 240)
            config.max_model_calls_per_task = 5
            self.assertEqual(task_limit(config, "rebuild"), 5)

    def test_budget_is_scoped_to_one_command(self):
        with tempfile.TemporaryDirectory() as directory:
            with usage_run(Path(directory), "generate", 1):
                reserve_call()
                with self.assertRaises(CallBudgetExceeded):
                    reserve_call()
            with usage_run(Path(directory), "generate", 1):
                reserve_call()

    def test_llm_records_usage_without_prompt_or_secrets(self):
        from engine import llm_client
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="正文"), finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18))
        model = SimpleNamespace(model_name="test", temperature=0.5, max_tokens=100, top_p=1)
        with tempfile.TemporaryDirectory() as directory, patch.object(llm_client, "get_client", return_value=client):
            root = Path(directory)
            with usage_run(root, "generate", 1):
                self.assertEqual(llm_client.chat(model, user_prompt="PRIVATE_PROMPT"), "正文")
                with self.assertRaises(CallBudgetExceeded):
                    llm_client.chat(model)
            data = (root / "cache/model_usage.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("PRIVATE_PROMPT", data)
            self.assertEqual(json.loads(data)["total_tokens"], 18)
            self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_empty_or_truncated_response_is_not_accepted(self):
        from engine import llm_client
        model = SimpleNamespace(model_name="test", temperature=0.5, max_tokens=100, top_p=1)
        for content, reason in (("", "stop"), ("半句", "length")):
            client = Mock()
            client.chat.completions.create.return_value = SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=reason)])
            with patch.object(llm_client, "get_client", return_value=client), self.assertRaises(ValueError):
                llm_client.chat(model, max_retries=1)


if __name__ == "__main__":
    unittest.main()
