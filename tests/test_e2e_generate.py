# 端到端集成测试：真实 cmd_generate 流水线 + LLM 全打桩（零成本、零网络）
# 验证 StoryKeeper 新机制的整链路产出与跨章上下文闭环。
# 运行: python -m unittest tests.test_e2e_generate -v

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import engine.novel_creator as novel_creator
import engine.settings as settings
import engine.llm_client as llm_client

PLAN = {
    "chapter_title": "废墟上的敲门声",
    "emotional_arc": [0.6, 0.9],
    "scene_outline": [
        {
            "scene_id": 1, "type": "breathable", "target_emotion": 0.6,
            "description": "沈渊检查奇点炉，发现裂缝变宽",
            "physical_mirror": "结霜的铁皮", "narrative_mirror": "",
            "sanity_score": 0.8,
        },
        {
            "scene_id": 2, "type": "breathable", "target_emotion": 0.9,
            "description": "沈渊回家，门外响起敲门声",
            "physical_mirror": "闪灭的走廊灯", "narrative_mirror": "",
            "sanity_score": 0.8,
        },
    ],
    "clue_operations": [],
    "entities": {
        "characters": ["沈渊"], "locations": ["零号废墟"],
        "objects": ["奇点炉"], "factions": [], "abilities": [], "clue_ids": [],
    },
    "chapter_hooks": {"light_hook": "门外传来敲门声", "dark_hook": "黑暗里有人盯住了他"},
}

SCENE1 = (
    "沈渊蹲在废墟边缘，用指节敲了敲奇点炉的外壳。\n"
    "铁皮上结着一层白霜，摸上去冻手。\n"
    "他把手套脱了，凑近观察接缝处那道裂纹。\n"
    "裂纹比三天前宽了半指。\n"
    "远处传来货船的汽笛声，一长两短。\n"
    "风卷着海腥味灌进废墟，吹得地上的碎纸打着转。\n"
    "沈渊把裂缝记进本子，站起身。\n"
    "他看了眼手表，距离交货还有四十分钟。"
)
SCENE2 = (
    "门里传出椅子拖动的声音。\n"
    "沈渊停住脚步，侧耳听。\n"
    "那声音停了一下，又响了。\n"
    "有人在。\n"
    "他把手按在门把上，没有动。\n"
    "走廊的灯闪了闪，暗下去。\n"
    "黑暗中，敲门声从他背后响起来。"
)

CH1_TEXT = SCENE1 + "\n\n" + SCENE2

# (marker, 返回类型, handler)；marker 必须唯一标识一类 LLM 调用
ROUTES = [
    ("番茄连载纪律", "chat", lambda p, s: CH1_TEXT),
    ("研究笔记", "chat", lambda p, s: "## 研究笔记\n- 沈渊在零号废墟。\n- 奇点炉外壳有裂缝。"),
    ("伏笔管家", "json", lambda p, s: {"operation_warnings": [], "overdue": [], "stale": [], "duplicates": []}),
    ("故事逻辑审稿人", "json", lambda p, s: {"passed": True, "errors": [], "suggestions": ""}),
    ("故事管理员", "json", lambda p, s: {
        "facts": [
            {"entity": "沈渊", "attribute": "位置", "value": "零号废墟"},
            {"entity": "奇点炉", "attribute": "状态", "value": "外壳有裂缝"},
        ],
        "arc_updates": [], "new_questions": ["奇点炉从何而来"], "resolved_question_ids": [],
    }),
    ("记忆压缩器", "json", lambda p, s: {
        "plot_progress": "沈渊在零号废墟检查奇点炉，发现裂缝变宽，记下后离开。",
        "emotion_state": "沈渊动作谨慎，呼吸平稳，警惕门外异响。",
        "env_and_clue": "零号废墟，结霜铁皮，货船汽笛，走廊灯闪灭。",
    }),
    ("声纹审计师", "json", lambda p, s: {"passed": True, "violations": []}),
    ("AI叙事", "json", lambda p, s: {"passed": True, "errors": []}),
    ("挤地铁", "json", lambda p, s: {
        "engagement_curve": [{"position": "0-600字", "understanding": 9, "interest": 8}],
        "confusion_points": [], "fatigue_points": [], "ai_suspect_points": [],
        "best_moment": "敲击奇点炉", "worst_moment": "", "would_continue": True,
        "overall_score": 7.5,
    }),
    ("current_chapter_snapshots", "json", lambda p, s: {
        "character_updates": {"沈渊": {"status_change": "检查奇点炉后返回", "location": "零号废墟"}},
        "clue_updates": {},
        "facts": [{"kind": "plot", "subject": "沈渊", "content": "在零号废墟检查奇点炉", "scene_id": 1}],
        "chapter_summary": "沈渊在零号废墟检查奇点炉，发现裂缝变宽，返回住处时门外响起敲门声。",
    }),
    ("设计大纲", "json", lambda p, s: PLAN),
]


def _build_fake(captured):
    def fake_chat(model_cfg, system_prompt="", user_prompt="", response_json=False,
                  max_retries=5):
        for marker, kind, handler in ROUTES:
            if marker in user_prompt:
                captured["calls"].append(marker)
                captured["prompts"].append((marker, user_prompt))
                value = handler(user_prompt, system_prompt)
                return json.dumps(value, ensure_ascii=False) if kind == "json" else value
        raise AssertionError(
            f"未识别的 LLM 调用（不应触达真实网络）: {user_prompt[:200]!r}")
    return fake_chat


class TestEndToEndGenerate(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="e2e-novels-")
        self.novels_dir = Path(self._tmp.name)
        self._creator_dir = novel_creator.NOVELS_DIR
        self._settings_dir = settings.NOVELS_DIR
        self._current = settings._current_novel
        self._config = settings._config
        self._orig_chat = llm_client.chat
        novel_creator.NOVELS_DIR = self.novels_dir
        settings.NOVELS_DIR = self.novels_dir
        self.captured = {"calls": [], "prompts": []}
        llm_client.chat = _build_fake(self.captured)

    def tearDown(self):
        llm_client.chat = self._orig_chat
        novel_creator.NOVELS_DIR = self._creator_dir
        settings.NOVELS_DIR = self._settings_dir
        settings._current_novel = self._current
        settings._config = self._config
        self._tmp.cleanup()

    def test_two_chapters_pipeline_produces_all_storykeeper_artifacts(self):
        novel_creator.create_novel(
            "e2e-book", "端到端验证书", 4, 1200, "科幻", "奇点炉与敲门声",
            model_env={"API_BASE_URL": "http://127.0.0.1:9/v1"},
        )
        settings.set_novel("e2e-book")
        import novel as novel_cli
        novel_cli.cmd_generate(1, overwrite=True, outline_override=True)
        novel_cli.cmd_generate(2, overwrite=True, outline_override=True)

        cfg = settings.get_config()

        # 正文产出
        for n in (1, 2):
            fp = cfg.generated_dir / f"chapter_{n:02d}.md"
            self.assertTrue(fp.exists(), f"chapter_{n:02d}.md 未生成")
            self.assertGreater(len(fp.read_text(encoding="utf-8")), 200)

        # StoryKeeper 全局状态
        state = json.loads((cfg.bible_dir / "story_state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["last_updated"], 2)
        self.assertEqual(
            state["facts"]["沈渊"]["位置"]["value"], "零号废墟")
        self.assertEqual(state["facts"]["沈渊"]["位置"]["chapters"], [1, 2])
        self.assertTrue(any("奇点炉" in q["text"] for q in state["open_questions"]))
        self.assertTrue(any(h["chapter"] == 1 for h in state["hook_log"]))

        # 章节级大纲追认
        timeline = (cfg.bible_dir / "actual_timeline.md").read_text(encoding="utf-8")
        self.assertIn("- 第1章", timeline)
        self.assertIn("- 第2章", timeline)

        # 跨章上下文闭环：planner 收到故事状态 + 实际轨迹；第2章 writer 收到上一章钩子
        planner_prompts = [p for m, p in self.captured["prompts"] if m == "设计大纲"]
        self.assertTrue(any("故事状态" in p and "禁止空降矛盾" in p for p in planner_prompts))
        self.assertTrue(any("已实际发生的叙事轨迹" in p for p in planner_prompts))
        writer_prompts = [p for m, p in self.captured["prompts"] if m == "番茄连载纪律"]
        self.assertGreaterEqual(len(writer_prompts), 4)  # 两章各 ≥1 场景
        self.assertTrue(any("上一章钩子" in p for p in writer_prompts[2:]))

        # 运行时知识库
        from engine.db import NovelDB
        db = NovelDB(cfg.bible_dir.parent)
        try:
            rows = db.conn.execute(
                "SELECT chapter FROM chapter_summaries WHERE chapter IN (1,2) ORDER BY chapter"
            ).fetchall()
            self.assertEqual([r["chapter"] for r in rows], [1, 2])
            facts = db.conn.execute(
                "SELECT chapter FROM chapter_facts WHERE chapter IN (1,2)").fetchall()
            self.assertGreaterEqual(len(facts), 1)
        finally:
            db.close()
        self.assertTrue((cfg.cache_dir / "keeper_cache_02.json").exists())

        # 全部 11 类 LLM 调用均被打桩路由，无一触达真实网络
        expected = {"设计大纲", "伏笔管家", "记忆压缩器", "AI叙事", "声纹审计师",
                    "故事逻辑审稿人", "故事管理员", "挤地铁", "current_chapter_snapshots",
                    "研究笔记", "番茄连载纪律"}
        self.assertTrue(
            expected <= set(self.captured["calls"]),
            f"流水线未覆盖全部调用: 缺 {sorted(expected - set(self.captured['calls']))}")


if __name__ == "__main__":
    unittest.main()
