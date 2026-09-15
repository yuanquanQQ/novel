import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import novel
from engine import novel_creator


OVERVIEW = "主角为查清旧案进入封闭小城，却因一次意外发现同伴隐瞒了关键证据。她联合守夜人追踪线索，在接连受阻后确认幕后势力正利用失踪者完成交易。关系裂痕与外部追杀同时加剧，主角被迫改变原计划，并在卷末夺回账册，却也因此暴露身份，引出下一卷更直接的对抗。"


def chapter_line(number, foreshadowing="无"):
    return (
        f"- **第{number}章 夜访**：林夏潜入仓库取得账册，导致守卫发现她的身份。"
        f"*功能：推进调查并制造追捕；伏笔：{foreshadowing}*"
    )


def valid_part(lo=1, hi=3):
    lines = ["### 卷概览", OVERVIEW, "", f"### 第{lo}-{hi}章：暗巷追踪"]
    lines.extend(chapter_line(number) for number in range(lo, hi + 1))
    return "\n".join(lines)


class TestOutlinePrompt(unittest.TestCase):
    def test_prompt_sets_exact_output_boundary_and_template(self):
        volume = {
            "name": "第一卷：迷城",
            "chapters": (1, 10),
            "core_emotion": "疑惧",
            "focus": "查明失踪案",
        }
        prompt = novel.build_outline_prompt(
            "测试书",
            volume,
            {"master_bible": "世界观", "characters": {}, "clues": {}},
            "加强人物冲突",
        )
        self.assertIn("只输出第一卷：迷城的卷内容", prompt)
        self.assertIn("### 卷概览", prompt)
        self.assertIn("### 第N-M章：小节名", prompt)
        self.assertIn("- **第N章 章名**：核心剧情（明确谁做什么导致什么）。*功能：", prompt)
        self.assertIn("每个章号恰好出现一次", prompt)
        self.assertIn("禁止在章节下添加二级 bullet", prompt)
        self.assertIn("【用户要求】加强人物冲突", prompt)

    def test_new_novel_template_uses_same_outline_contract(self):
        system = novel_creator._prompts("测试书", "悬疑", "简介")["outline_generator"]["system"]
        self.assertIn("只输出本卷内容", system)
        self.assertIn("### 卷概览", system)
        self.assertIn("- **第N章 章名**：核心剧情（明确谁做什么导致什么）。*功能：", system)
        self.assertIn("每个章号恰好出现一次", system)
        self.assertIn("禁止章节下附加二级bullet", system)


class TestOutlineValidator(unittest.TestCase):
    def test_accepts_exact_short_volume_template(self):
        self.assertEqual(novel.validate_outline_output(valid_part(), 1, 3), [])

    def test_reports_missing_duplicate_out_of_range_and_bad_lines(self):
        content = "\n".join([
            "## 第一卷（第1-3章）",
            "### 卷概览",
            OVERVIEW,
            "### 第1-3章：暗巷追踪",
            chapter_line(1),
            chapter_line(1),
            "  - 补充说明",
            chapter_line(4),
            "自查：章节齐全",
        ])
        errors = novel.validate_outline_output(content, 1, 3)
        joined = "\n".join(errors)
        self.assertIn("H2卷标题", joined)
        self.assertIn("自查文本", joined)
        self.assertIn("缺失章号：2、3", joined)
        self.assertIn("重复章号：1", joined)
        self.assertIn("越界章号：4", joined)
        self.assertIn("只接受小节标题和顶层单行章节bullet", joined)

    def test_rejects_non_exact_chapter_bullet_and_bad_overview(self):
        content = "\n".join([
            "### 卷概览",
            "太短。",
            "### 第1-1章：开端",
            "- 第1章 夜访：林夏进入仓库。功能：推进；伏笔：无",
        ])
        errors = "\n".join(novel.validate_outline_output(content, 1, 1))
        self.assertIn("实际3字", errors)
        self.assertIn("缺失章号：1", errors)
        self.assertIn("只接受小节标题和顶层单行章节bullet", errors)

    def test_retry_feedback_contains_concrete_validation_errors(self):
        calls = []
        responses = ["格式错误", valid_part()]

        def fake_chat(model, user_prompt):
            calls.append(user_prompt)
            return responses.pop(0)

        result = novel._generate_valid_outline_part(fake_chat, object(), "初始提示", 1, 3)
        self.assertEqual(result, valid_part())
        self.assertEqual(len(calls), 2)
        self.assertIn("缺失章号：1、2、3", calls[1])
        self.assertIn("上次输出", calls[1])

    def test_invalid_final_result_does_not_overwrite_outline(self):
        with tempfile.TemporaryDirectory() as tmp:
            bible_dir = Path(tmp)
            outline_file = bible_dir / "outline.md"
            outline_file.write_text("原大纲", encoding="utf-8")
            config = SimpleNamespace(
                bible_dir=bible_dir,
                story_title="测试书",
                planner_model=object(),
                volume_config={
                    "volume_1": {
                        "name": "第一卷",
                        "chapters": (1, 1),
                        "core_emotion": "紧张",
                        "focus": "推进主线",
                    }
                },
            )
            with patch.object(novel, "get_config", return_value=config), patch(
                "engine.llm_client.chat", return_value="坏格式"
            ) as chat:
                with self.assertRaises(novel.OutlineValidationError):
                    novel.cmd_outline()
            self.assertEqual(chat.call_count, 3)
            self.assertEqual(outline_file.read_text(encoding="utf-8"), "原大纲")

    def test_1500_chapters_are_small_parts_and_resume(self):
        def output_for_prompt(model, user_prompt):
            lo, hi = map(int, re.search(r"【当前分片】第(\d+)-(\d+)章", user_prompt).groups())
            lines = []
            if "本片是本卷首片" in user_prompt:
                lines.extend(["### 卷概览", OVERVIEW, ""])
            lines.append(f"### 第{lo}-{hi}章：阶段推进")
            lines.extend(chapter_line(number) for number in range(lo, hi + 1))
            return "\n".join(lines)

        with tempfile.TemporaryDirectory() as tmp:
            bible_dir = Path(tmp)
            config = SimpleNamespace(
                bible_dir=bible_dir, story_title="长书", planner_model=object(),
                volume_config=novel_creator._volume_config(1500),
            )
            for volume in config.volume_config.values():
                volume["core_emotion"] = "紧张"
                volume["focus"] = "推进主线"
            with patch.object(novel, "get_config", return_value=config), patch.object(
                    novel, "get_novel", return_value="long-book"), patch(
                    "engine.llm_client.chat", side_effect=output_for_prompt) as chat:
                novel.cmd_outline()
                first_calls = chat.call_count
                novel.cmd_outline()
            self.assertEqual(chat.call_count, first_calls)
            manifest = json.loads((bible_dir / "outline_manifest.json").read_text(encoding="utf-8"))
            ranges = [item["range"] for item in manifest["parts"]]
            self.assertEqual(ranges[0][0], 1)
            self.assertEqual(ranges[-1][1], 1500)
            self.assertTrue(all(8 <= hi - lo + 1 <= 20 for lo, hi in ranges))
            self.assertTrue(all(item["status"] == "complete" and item["hash"]
                                for item in manifest["parts"]))
            outline = (bible_dir / "outline.md").read_text(encoding="utf-8")
            self.assertEqual(len(set(map(int, re.findall(r"\*\*第(\d+)章", outline)))), 1500)
            self.assertEqual(outline.count("### 卷概览"), len(config.volume_config))


if __name__ == "__main__":
    unittest.main()
