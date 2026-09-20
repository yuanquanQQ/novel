# engine/style_kit/scanner.py 单元测试（stdlib unittest）
# 运行: python -m unittest tests.test_scanner -v

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.style_kit import scanner


class TestScanner(unittest.TestCase):

    def test_clean_text_passes(self):
        text = (
            "他把工牌塞进兜里，出门左拐。\n\n"
            "“你昨儿不是说要加班？”\n\n"
            "“加个屁。”他没回头，“粥在锅里，自己盛。”\n\n"
            "楼道声控灯坏了仨月，他摸着扶手往下走。"
        )
        r = scanner.scan(text)
        self.assertTrue(r.passed, r.to_suggestions())

    def test_banned_word_caught(self):
        r = scanner.scan("他然而转身，目光如炬地看着对方。")
        pats = [v["pattern"] for v in r.warnings]
        self.assertIn("然而", pats)
        self.assertIn("目光如炬", pats)
        self.assertTrue(r.passed)

    def test_ai_pattern_shi_beats(self):
        # 「不是…而是」已由 hard 降为 soft(≤1)：单次不违规，两次及以上才给提示
        single = scanner.scan("这不是失败，而是另一种开始。")
        self.assertTrue(single.passed, single.to_suggestions())
        self.assertNotIn("bushi_ershi", [v["pattern"] for v in single.violations])
        double = scanner.scan("这不是失败，而是另一种开始，也不是终点，而是起点。")
        warn_ids = [w["pattern"] for w in double.warnings]
        self.assertIn("bushi_ershi", warn_ids)
        self.assertTrue(double.passed)

    def test_dash_violation(self):
        # 破折号已由 hard(0) 降为 soft(≤2)：一次不违规，三次及以上才给提示
        single = scanner.scan("门开了——外面站着一个人。")
        self.assertTrue(single.passed, single.to_suggestions())
        self.assertNotIn("pofihao", [v["pattern"] for v in single.violations])
        triple = scanner.scan("门开了——她进来——灯亮了——影子拉得很长。")
        warn_ids = [w["pattern"] for w in triple.warnings]
        self.assertIn("pofihao", warn_ids)
        self.assertTrue(triple.passed)

    def test_softened_patterns_are_warnings_not_violations(self):
        # 两个被放松的模式永远只出现在 warnings，绝不进 violations（不打回）
        r = scanner.scan(
            "这不是失败，而是另一种开始。"
            "也不是终点，而是起点。"
            "门开了——她进来——灯亮了——影子拉得很长。"
        )
        self.assertTrue(r.passed, r.to_suggestions())
        self.assertNotIn("bushi_ershi", [v["pattern"] for v in r.violations])
        self.assertNotIn("pofihao", [v["pattern"] for v in r.violations])

    def test_soft_word_threshold(self):
        one = "这里仿佛起雾了。"
        many = "仿佛起雾。仿佛下雨。仿佛天塌。仿佛海干。仿佛雾再来。"
        clean = scanner.scan(one)
        dirty = scanner.scan(many)
        self.assertFalse(any(w["pattern"] == "仿佛" for w in clean.warnings))
        self.assertTrue(any(w["pattern"] == "仿佛" for w in dirty.warnings))
        self.assertTrue(dirty.passed)  # soft 级不打回

    def test_halfwidth_quote_caught(self):
        r = scanner.scan('他说"进来吧"，然后低头吃饭。')
        pats = [v["pattern"] for v in r.violations]
        self.assertIn("半角引号", pats)

    def test_dialogue_ratio_metric(self):
        text = "“走不走。”“再等等。”“等什么。”“等粥凉。”\n他搅着碗里的粥。"
        r = scanner.scan(text)
        self.assertGreater(r.metrics["dialogue_ratio"], 0.3)

    def test_corner_quotes_require_chinese_double_quotes(self):
        r = scanner.scan("「他说『快走』，你没听见？」")
        self.assertFalse(r.passed)
        self.assertIn("直角引号", [v["pattern"] for v in r.violations])
        self.assertIn("“”", r.to_suggestions())

    def test_nested_chinese_quotes_pass(self):
        self.assertTrue(scanner.scan("“他说‘快走’，你没听见？”").passed)

    def test_optional_ratio_check_recognizes_double_quotes(self):
        rules = {"enforce_dialogue_ratio": True, "metrics": {"dialogue_ratio_min": 0.9}}
        r = scanner.scan("他端起桌上的水，喝了一大口，擦干手指才问：“走吗？”", rules)
        self.assertIn("dialogue_low", [w["pattern"] for w in r.warnings])

    def test_ellipsis_pile_caught(self):
        r = scanner.scan("他走了……她没追……风停了……灯灭了。")
        pats = [v["pattern"] for v in r.warnings]
        self.assertIn("省略号堆砌", pats)

    def test_to_rows_shape(self):
        r = scanner.scan("他然而站住。")
        rows = r.to_rows(chapter=9)
        self.assertTrue(rows)
        self.assertEqual(rows[0][0], 9)


if __name__ == "__main__":
    unittest.main()
