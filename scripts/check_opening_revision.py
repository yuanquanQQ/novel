"""Check the installed opening against its reviewed source and knowledge hashes."""
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.knowledge import check_ready, content_hash
from engine.quality import word_count
from engine.settings import get_config, get_novel_dir, set_novel
from engine.style_kit.scanner import scan


def main():
    set_novel("xinghai-zhumingshi")
    config = get_config()
    root = get_novel_dir()
    marker = json.loads((config.bible_dir / "opening_revision_v2.json").read_text(encoding="utf-8"))
    backup = Path(marker["backup"])
    assert (backup / "manifest.json").is_file(), "Original backup missing"
    checked = []
    db_uri = (root / "db/novel.db").as_uri() + "?mode=ro"
    with closing(sqlite3.connect(db_uri, uri=True)) as db:
        for chapter in (1, 2, 3):
            filename = f"chapter_{chapter:02d}.md"
            text = (config.generated_dir / filename).read_text(encoding="utf-8")
            digest = content_hash(text)
            assert digest == marker["source_hashes"][str(chapter)], f"Chapter {chapter} changed after installation"
            assert text == (ROOT / "revisions/xinghai-opening" / filename).read_text(encoding="utf-8")
            cache = json.loads((config.cache_dir / f"keeper_cache_{chapter:02d}.json").read_text(encoding="utf-8"))
            assert cache["source_hash"] == digest, f"Chapter {chapter} cache mismatch"
            summary_hash = db.execute("SELECT content_hash FROM chapter_summaries WHERE chapter=?", (chapter,)).fetchone()
            assert summary_hash == (digest,), f"Chapter {chapter} summary mismatch"
            assert scan(text).passed, f"Chapter {chapter} format failure"
            assert 2250 <= word_count(text) <= 3750, f"Chapter {chapter} word budget failure"
            checked.append({"chapter": chapter, "words": word_count(text), "body_cache_db_match": True})
    state = json.loads((config.bible_dir / "story_state.json").read_text(encoding="utf-8"))
    assert state["last_updated"] >= 3
    assert state["facts"]["沈渊"]["印记位置"]["value"] == "左掌"
    timeline = (config.bible_dir / "actual_timeline.md").read_text(encoding="utf-8")
    chapters = list(map(int, re.findall(r"^- 第(\d+)章", timeline, re.MULTILINE)))
    assert chapters == sorted(set(chapters)) and chapters[:3] == [1, 2, 3]
    check_ready(config, 4)
    print(json.dumps({"chapters": checked, "chapter_4_ready": True, "backup": str(backup)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
