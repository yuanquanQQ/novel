# 模型配置 API + 出厂模板测试
# 运行: python -m unittest tests.test_model_config -v

import json
import os
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
import server.app as server_app
from engine import model_config

LEGACY_CONFIG = '''import os
from dataclasses import dataclass, field
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent

def _get_api_key():
    return os.getenv("DEEPSEEK_API_KEY", "legacy-key")

@dataclass
class ModelConfig:
    model_name: str = "deepseek-chat"
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 0.9

@dataclass
class Config:
    deepseek_api_key: str = field(default_factory=_get_api_key)
    deepseek_base_url: str = "http://legacy.example/v1"
    planner_model: ModelConfig = field(default_factory=lambda: ModelConfig(model_name="legacy-planner"))
    researcher_model: ModelConfig = field(default_factory=ModelConfig)
    writer_model: ModelConfig = field(default_factory=ModelConfig)
    immediate_reviewer_model: ModelConfig = field(default_factory=ModelConfig)
    heavy_reviewer_model: ModelConfig = field(default_factory=ModelConfig)
    keeper_model: ModelConfig = field(default_factory=ModelConfig)
    archivist_model: ModelConfig = field(default_factory=ModelConfig)
    foreshadowing_steward_model: ModelConfig = field(default_factory=ModelConfig)
    reader_proxy_model: ModelConfig = field(default_factory=ModelConfig)
    marketer_model: ModelConfig = field(default_factory=ModelConfig)
    story_title: str = "旧书"
    chapter_count: int = 200
    words_per_chapter: int = 3000
    language: str = "zh-CN"
    volume_config: dict = field(default_factory=lambda: {
        "volume_1": {"name": "第一卷", "chapters": (1, 100),
                     "core_emotion": "起", "focus": "展开"},
        "volume_2": {"name": "第二卷", "chapters": (101, 200),
                     "core_emotion": "承", "focus": "收束"},
    })
    bible_dir: Path = PROJECT_ROOT / "bible"
    generated_dir: Path = PROJECT_ROOT / "generated"
    cache_dir: Path = PROJECT_ROOT / "cache"
    immediate_review_max_retries: int = 3
    heavy_review_interval: int = 5

config = Config()
'''


class ModelConfigTestCase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.novels_dir = Path(self._tmp.name) / "novels"
        self.novels_dir.mkdir()
        self._saved = (novel_creator.NOVELS_DIR, server_app.NOVELS_DIR,
                       settings.NOVELS_DIR, model_config.NOVELS_DIR)
        novel_creator.NOVELS_DIR = self.novels_dir
        server_app.NOVELS_DIR = self.novels_dir
        settings.NOVELS_DIR = self.novels_dir
        model_config.NOVELS_DIR = self.novels_dir
        self.client = TestClient(server_app.app)

    def tearDown(self):
        (novel_creator.NOVELS_DIR, server_app.NOVELS_DIR,
         settings.NOVELS_DIR, model_config.NOVELS_DIR) = self._saved
        self._tmp.cleanup()


class TestExpandAndSanitize(ModelConfigTestCase):

    def test_expand_quick_maps_roles(self):
        out = model_config.expand_quick({
            "api_key": "sk-test1234567890", "base_url": "http://x/v1",
            "chat_model": "gpt-lite", "reasoner_model": "r1",
        })
        self.assertEqual(out["API_KEY"], "sk-test1234567890")
        self.assertEqual(out["WRITER_MODEL"], "gpt-lite")
        self.assertEqual(out["PLANNER_MODEL"], "r1")
        self.assertEqual(out["THEME_MODEL"], "gpt-lite")
        self.assertEqual(out["HEAVY_REVIEWER_MODEL"], "r1")

    def test_sanitize_accepts_attr_and_env_keys_rejects_unknown(self):
        out = model_config.sanitize_input({"writer_model": "a", "PLANNER_MODEL": "b"})
        self.assertEqual(out, {"WRITER_MODEL": "a", "PLANNER_MODEL": "b"})
        with self.assertRaises(model_config.ModelConfigError):
            model_config.sanitize_input({"RM -rf": "evil"})
        with self.assertRaises(model_config.ModelConfigError):
            model_config.sanitize_input({"WRITER_MODEL": "line1\nline2"})
        with self.assertRaises(model_config.ModelConfigError):
            model_config.sanitize_input({"API_KEY": "inject=extra"})

    def test_update_env_merges_and_preserves_unknown(self):
        p = self.novels_dir / "t.env"
        p.write_text("# 用户注释\nAPI_KEY=sk-1\nSOME_FUTURE_KEY=keepme\n", encoding="utf-8")
        model_config.update_env_file(p, {"API_KEY": "sk-2"})
        env = model_config.read_env_file(p)
        self.assertEqual(env, {"API_KEY": "sk-2", "SOME_FUTURE_KEY": "keepme"})
        raw = p.read_text(encoding="utf-8")
        self.assertIn("# 用户注释", raw)              # 注释保留
        self.assertEqual(raw.count("API_KEY="), 1)     # 原位替换不重复


class TestCreateWithModel(ModelConfigTestCase):

    def test_create_novel_writes_env_and_api_returns_view(self):
        r = self.client.post("/api/novels", json={
            "id": "quick-book", "title": "快书", "chapter_count": 6,
            "words_per_chapter": 2000,
            "model": {"quick": {"api_key": "sk-abcdef123456", "chat_model": "m-chat",
                                "reasoner_model": "m-reason"}},
        })
        self.assertEqual(r.status_code, 201, r.text)
        env = model_config.read_env_file(self.novels_dir / "quick-book" / ".env")
        self.assertEqual(env["WRITER_MODEL"], "m-chat")
        self.assertEqual(env["PLANNER_MODEL"], "m-reason")

        view = self.client.get("/api/novels/quick-book/model-config").json()
        self.assertFalse(view["api_key_masked"].startswith("sk"))
        self.assertIn("3456", view["api_key_masked"])
        self.assertNotIn("sk-abcdef123456", json.dumps(view))  # 绝不明文回传
        self.assertTrue(view["env_supported"])
        writer = [x for x in view["roles"] if x["attr"] == "writer_model"][0]
        self.assertEqual(writer["model"], "m-chat")

    def test_create_rejects_unknown_model_key(self):
        r = self.client.post("/api/novels", json={
            "id": "bad-book", "title": "坏书", "chapter_count": 2,
            "words_per_chapter": 100,
            "model": {"models": {"EVIL_KEY": "x"}},
        })
        self.assertEqual(r.status_code, 400)

    def test_put_update_partial_key_kept(self):
        self.client.post("/api/novels", json={
            "id": "edit-book", "title": "改书", "chapter_count": 2,
            "words_per_chapter": 100,
            "model": {"quick": {"api_key": "sk-keep00001111", "reasoner_model": "r-old"}},
        })
        r = self.client.put("/api/novels/edit-book/model-config", json={
            "models": {"PLANNER_MODEL": "r-new"},   # 不带 api_key → 保持
        })
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertTrue(data["ok"])
        env = model_config.read_env_file(self.novels_dir / "edit-book" / ".env")
        self.assertEqual(env["PLANNER_MODEL"], "r-new")
        self.assertEqual(env["API_KEY"], "sk-keep00001111")
        self.assertEqual(env["RESEARCHER_MODEL"], "r-old")  # quick 展开过的别的键不动

    def test_legacy_novel_upgraded_on_save(self):
        book = self.novels_dir / "old-book"
        (book / "bible").mkdir(parents=True)
        (book / "config.py").write_text(LEGACY_CONFIG, encoding="utf-8")
        view = self.client.get("/api/novels/old-book/model-config").json()
        self.assertFalse(view["env_supported"])
        self.assertEqual(view["base_url"], "http://legacy.example/v1")

        r = self.client.put("/api/novels/old-book/model-config", json={
            "quick": {"chat_model": "new-chat"},
        })
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertTrue(data["upgraded_config"])
        self.assertTrue((book / "config.py.bak").is_file())
        cfg = settings.load_config("old-book")
        self.assertEqual(cfg.writer_model.model_name, "new-chat")
        self.assertEqual(cfg.story_title, "旧书")        # 书名保留
        self.assertEqual(dict(cfg.volume_config)["volume_2"]["name"], "第二卷")  # 卷结构保留
        self.assertEqual(cfg.chapter_count, 200)


class TestFactoryPrompts(ModelConfigTestCase):
    """出厂人味模板：token 注入后完整、format 可填、无非法花括号。"""

    def get_prompts(self):
        path = novel_creator.create_novel("prompt-book", "模板书", 3, 1000, "都市", "简介")
        return json.loads((path / "novel_prompts.json").read_text(encoding="utf-8"))

    def test_writer_receives_style_kit(self):
        prompts = self.get_prompts()
        settings.set_novel("prompt-book")
        from engine import prompts_loader
        prompts_loader.reload()
        system, _ = prompts_loader.get_prompt("writer")
        self.assertIn("句式情绪同步", system)
        self.assertIn("番茄连载纪律", system)
        out = system.format(novel_title="T", chapter_num=1, scene_id=1,
                            keeper_cache="K", scene_plan="S",
                            characters_voice_print="V", research_context="R",
                            chapter_hooks="H", special_condition="X",
                            style_watch="W")
        self.assertIn("句式情绪同步", out)
        self.assertNotIn("[STYLE_FORBIDDEN]", out)
        self.assertNotIn("{keeper_cache}", out)

    def test_reviewer_and_auditor_placeholders(self):
        prompts = self.get_prompts()
        settings.set_novel("prompt-book")
        from engine import prompts_loader
        prompts_loader.reload()
        ri, _ = prompts_loader.get_prompt("reviewer_immediate")
        out = ri.format(keeper_cache="K", draft="草稿")
        self.assertIn("草稿", out)
        self.assertIn('"passed"', out)          # {{ 已还原为 {
        da, _ = prompts_loader.get_prompt("dialogue_auditor")
        out2 = da.format(voice_print="V", draft="D")
        self.assertIn("V", out2)
        kp, _ = prompts_loader.get_prompt("keeper")
        out3 = kp.format(scene_draft="正文…", scene_id=2)
        self.assertIn("正文…", out3)
        st, _ = prompts_loader.get_prompt("foreshadowing_steward")
        out4 = st.format(all_foreshadowing="A", plan_json="P", clue_operations="O",
                         recent_summaries="R", chapter_num=3)
        self.assertIn("A", out4)
        rd, _ = prompts_loader.get_prompt("reader_proxy")
        self.assertIn("章", rd.format(full_chapter="章节内容"))

    def test_planner_template_has_bible_placeholders(self):
        prompts = self.get_prompts()
        tpl = prompts["planner"]["chapter_template"]
        for ph in ("{master_bible}", "{characters_json}", "{clues_json}",
                  "{lessons_learned}", "{outline_summary}"):
            self.assertIn(ph, tpl, f"planner 模板缺 {ph}")

    def test_test_endpoint_reports_failure_without_network(self):
        novel_creator.create_novel("prompt-book", "模板书", 3, 1000, "都市", "简介")
        # 指向不存在的服务端口，测试仅验证返回结构，零外部调用
        with patch.dict(os.environ, {"API_KEY": "sk-fake"}, clear=False):
            r = self.client.post("/api/novels/prompt-book/model-config/test",
                                 json={"model": "x", "base_url": "http://127.0.0.1:9/v1"})
        body = r.json()
        self.assertIn("ok", body)
        self.assertFalse(body["ok"])
        self.assertTrue(body.get("error"))


if __name__ == "__main__":
    unittest.main()
