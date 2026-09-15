import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from engine.chapter_files import chapter_files, parse_chapter_number
from engine.agents.planner import ENTITY_FIELDS, PlannerAgent, parse_outline_context
from engine.agents.researcher import ResearcherAgent, entity_search_terms


def outline_line(number):
    return (
        f"- **第{number}章 夜访**：林夏进入仓库取得账册。"
        "*功能：推进调查；伏笔：无*"
    )


class ChapterFilesTests(unittest.TestCase):
    def test_numeric_sort_filter_and_strict_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for number in (1000, 100, 999, 99):
                (directory / f"chapter_{number}.md").write_text(
                    str(number), encoding="utf-8"
                )
            (directory / "chapter_100.md.bak").write_text("x", encoding="utf-8")
            (directory / "chapter_bad.md").write_text("x", encoding="utf-8")

            paths = chapter_files(directory)
            self.assertEqual(
                [parse_chapter_number(path) for path in paths],
                [99, 100, 999, 1000],
            )
            self.assertEqual(
                [parse_chapter_number(path) for path in chapter_files(
                    directory, before_chapter=1000
                )],
                [99, 100, 999],
            )
            self.assertEqual(
                [parse_chapter_number(path) for path in chapter_files(
                    directory, before_chapter=1000, limit=2
                )],
                [100, 999],
            )


class PlannerLongContextTests(unittest.TestCase):
    def test_outline_parser_returns_section_current_and_two_neighbors(self):
        outline = "\n".join([
            "## 第一卷（第98-103章）",
            "### 第98-103章：暗巷追踪",
            *(outline_line(number) for number in range(98, 104)),
            "  - **第104章 错误缩进**：不应解析。*功能：无；伏笔：无*",
        ])
        context = parse_outline_context(outline, 100)
        self.assertEqual(context["section"], "### 第98-103章：暗巷追踪")
        self.assertEqual(
            [item["chapter"] for item in context["neighbors"]],
            [98, 99, 100, 101, 102],
        )
        self.assertEqual(context["current"], outline_line(100))

    def test_prompt_reads_outline_but_never_current_or_future_drafts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bible_dir = root / "bible"
            generated_dir = root / "generated"
            bible_dir.mkdir()
            generated_dir.mkdir()
            (bible_dir / "outline.md").write_text(
                "### 第98-102章：交锋\n" +
                "\n".join(outline_line(number) for number in range(98, 103)),
                encoding="utf-8",
            )
            for number in (99, 100, 101):
                (generated_dir / f"chapter_{number}.md").write_text(
                    f"正文标记{number}\n内容", encoding="utf-8"
                )
            fake_config = SimpleNamespace(
                planner_model=object(),
                bible_dir=bible_dir,
                generated_dir=generated_dir,
                volume_config={"v": {
                    "chapters": (1, 200), "name": "卷", "core_emotion": "紧张",
                    "focus": "推进",
                }},
            )
            template = (
                "{master_bible}{characters_json}{clues_json}{motif_bank_json}"
                "{lessons_learned}{outline_summary}{chapter_num}{instruction}"
                "{volume_name}{volume_emotion}{volume_focus}"
            )
            with patch("engine.agents.planner.config", fake_config), patch(
                "engine.prompts_loader.get_prompt", return_value=(
                    "第{chapter_num}章 {novel_title}", template
                )
            ), patch("engine.prompts_loader.get_meta", return_value={"novel": "测试"}):
                planner = PlannerAgent()
                prompt = planner._build_prompt(100, "继续", {}, [])

            self.assertIn(outline_line(100), prompt)
            self.assertIn("正文标记99", prompt)
            self.assertNotIn("正文标记100", prompt)
            self.assertNotIn("正文标记101", prompt)
            self.assertIn("characters、locations、objects", prompt)

    def test_normalize_supplies_complete_entities_shape(self):
        planner = PlannerAgent.__new__(PlannerAgent)
        normalized = planner._validate_and_normalize({
            "entities": {"characters": ["林夏", "林夏", 3], "objects": "账册"},
            "scene_outline": [{}],
        }, 7)
        self.assertEqual(set(normalized["entities"]), set(ENTITY_FIELDS))
        self.assertEqual(normalized["entities"]["characters"], ["林夏"])
        self.assertEqual(normalized["entities"]["objects"], [])
        missing = planner._validate_and_normalize({"scene_outline": [{}]}, 8)
        self.assertTrue(all(value == [] for value in missing["entities"].values()))


class ResearcherEntityTests(unittest.TestCase):
    def test_entity_terms_prioritize_all_entity_types_and_character_names(self):
        plan = {"entities": {
            "characters": ["林夏"], "locations": ["旧仓库"],
            "objects": ["账册"], "factions": ["守夜人"],
            "abilities": ["听风"], "clue_ids": ["F001"],
        }}
        names, terms = entity_search_terms(plan, ["林夏", "周明"])
        self.assertEqual(names, ["林夏"])
        self.assertEqual(
            set(terms), {"林夏", "旧仓库", "账册", "守夜人", "听风", "F001"}
        )

    def test_run_filters_characters_and_clues_without_calling_llm(self):
        plan = {
            "entities": {
                "characters": ["林夏"], "locations": ["旧仓库"],
                "objects": [], "factions": [], "abilities": [],
                "clue_ids": ["C001"],
            },
            "clue_operations": [{"clue_id": "F001"}],
        }
        bible = {
            "characters": {"characters": {
                "林夏": {"current_location": "旧仓库"},
                "周明": {"current_location": "医院"},
            }},
            "clues": {
                "clues": {"C001": {"name": "账册"}, "C002": {"name": "钥匙"}},
                "active_foreshadowing": {
                    "F001": {"status": "pending"}, "F002": {"status": "pending"}
                },
            },
        }
        researcher = ResearcherAgent.__new__(ResearcherAgent)
        researcher.model_config = object()
        with patch.object(researcher, "_build_research_notes", return_value="notes"), patch.object(
            researcher, "_db_context", return_value={}
        ), patch.object(researcher, "_read_recent_summaries", return_value="recent"):
            result = researcher.run(plan, 10, bible)
        self.assertEqual(list(result["relevant_characters"]), ["林夏"])
        self.assertEqual(list(result["relevant_clues"]), ["C001"])
        self.assertEqual(list(result["relevant_foreshadowing"]), ["F001"])
        self.assertNotIn("医院", result["relevant_locations"])

    def test_missing_entities_keeps_legacy_full_json_context(self):
        bible = {
            "characters": {"characters": {"林夏": {}, "周明": {}}},
            "clues": {
                "clues": {"C001": {}, "C002": {}},
                "active_foreshadowing": {"F001": {"status": "pending"}},
            },
        }
        researcher = ResearcherAgent.__new__(ResearcherAgent)
        researcher.model_config = object()
        with patch.object(researcher, "_build_research_notes", return_value="notes"), patch.object(
            researcher, "_db_context", return_value={}
        ), patch.object(researcher, "_read_recent_summaries", return_value="recent"):
            result = researcher.run({"scene_outline": []}, 10, bible)
        self.assertEqual(set(result["relevant_characters"]), {"林夏", "周明"})
        self.assertEqual(set(result["relevant_clues"]), {"C001", "C002"})


if __name__ == "__main__":
    unittest.main()
