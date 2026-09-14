# engine/db.py 单元测试
# 运行: python -m unittest tests.test_db -v

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.db import NovelDB


def make_bible(tmp: Path):
    b = tmp / "bible"
    b.mkdir(parents=True)
    (b / "characters.json").write_text(json.dumps({
        "characters": {
            "林泽": {"role": "主角", "voice_print": "简洁", "first_appearance_chapter": 1},
            "叶清": {"role": "女一", "voice_print": "温柔", "first_appearance_chapter": 1},
        }}, ensure_ascii=False), encoding="utf-8")
    (b / "clues.json").write_text(json.dumps({
        "clues": {"C001": {"name": "车祸真相", "type": "主线", "introduced_chapter": 1,
                            "intended_reveal_chapter": 46, "description": "x"}},
        "active_foreshadowing": {
            "F001": {"name": "永不反射镜", "status": "pending", "introduced_chapter": 1,
                     "intended_payoff_chapter": 126, "description": "d"},
            "F002": {"name": "已埋待收", "status": "pending", "introduced_chapter": 2,
                     "intended_payoff_chapter": 5, "description": "d2"},
        }}, ensure_ascii=False), encoding="utf-8")
    (b / "motif_bank.json").write_text(json.dumps({
        "motifs": [{"id": "M1", "name": "水洼倒影", "used_in_chapters": [1]}]},
        ensure_ascii=False), encoding="utf-8")
    (b / "lessons_learned.jsonl").write_text(
        json.dumps({"chapter": 1, "issue": "节奏快", "fix": "用户手动修订"},
                   ensure_ascii=False) + "\n", encoding="utf-8")
    g = tmp / "generated"
    g.mkdir()
    (g / "chapter_01.md").write_text("正文" * 800, encoding="utf-8")


class TestNovelDB(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        make_bible(self.tmp)
        self.db = NovelDB(self.tmp)

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_import_bible_counts(self):
        c = self.db.import_bible()
        self.assertEqual(c["characters"], 2)
        self.assertEqual(c["foreshadowing"], 2)
        self.assertEqual(c["clues"], 1)
        self.assertEqual(c["chapter_log"], 1)

    def test_import_idempotent_and_preserves_status(self):
        self.db.import_bible()
        self.db.resolve_foreshadow("F001", 50)
        self.db.import_bible()  # 二次导入不得复活已回收伏笔
        st = self.db.conn.execute(
            "SELECT status, resolved_ch FROM foreshadowing WHERE id='F001'").fetchone()
        self.assertEqual(st["status"], "resolved")
        self.assertEqual(st["resolved_ch"], 50)

    def test_style_hits_dedup(self):
        self.db.add_style_hits([(3, "禁用词", "然而", 2), (3, "句式", "pofihao", 5)])
        self.db.add_style_hits([(3, "禁用词", "然而", 1)])
        top = self.db.top_style_hits()
        hit = [dict(t) for t in top if t["pattern"] == "然而"][0]
        self.assertEqual(hit["total"], 1)  # 覆盖式更新而非累加

    def test_facts_search(self):
        self.db.import_bible()
        self.db.add_facts(2, [{"kind": "object", "subject": "黑猫",
                               "content": "叼来银色颈圈", "scene_id": 1},
                              {"kind": "injury", "subject": "林泽",
                               "content": "虎口渗银色液体"}])
        rows = self.db.search_facts(["银色"], before_ch=5)
        self.assertEqual(len(rows), 2)
        self.db.add_facts(2, [{"kind": "object", "subject": "黑猫",
                               "content": "叼来银色颈圈", "scene_id": 1}])
        self.assertEqual(len(self.db.search_facts(["银色"], 5)), 2)  # UNIQUE 去重

    def test_open_foreshadowing_buckets(self):
        self.db.import_bible()
        buckets = self.db.open_foreshadowing(current_ch=100, stale_after=30)
        ids_overdue = [f["id"] for f in buckets["overdue_to_payoff"]]
        ids_stale = [f["id"] for f in buckets["stale"]]
        self.assertIn("F002", ids_overdue)   # payoff_ch=5 < 100 未回收
        self.assertIn("F001", ids_stale)     # planted=1, 暗了99章

    def test_chapter_log_upsert_merges(self):
        self.db.import_bible()
        self.db.log_chapter(1, reader_score=7.5, would_continue=True, violations=2)
        r = self.db.conn.execute(
            "SELECT * FROM chapter_log WHERE chapter=1").fetchone()
        self.assertEqual(r["words"], 1600)          # 导入的字数保留
        self.assertEqual(r["reader_score"], 7.5)    # 新字段并入

    def test_hint_foreshadow_timeline(self):
        self.db.import_bible()
        self.db.hint_foreshadow("F001", 10)
        self.db.hint_foreshadow("F001", 10)
        self.db.hint_foreshadow("F001", 23)
        row = self.db.conn.execute(
            "SELECT hinted_chs FROM foreshadowing WHERE id='F001'").fetchone()
        self.assertEqual(json.loads(row["hinted_chs"]), [1, 10, 23])


if __name__ == "__main__":
    unittest.main()
