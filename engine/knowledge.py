"""Recoverable publication and chronological knowledge rebuilding.

Callers must hold the per-novel operation lock. A durable journal prevents writing
through an interrupted archive; recover restores the last consistent snapshot.
"""

import hashlib
import json
import os
import shutil
import sqlite3
import uuid
from contextlib import closing, contextmanager
from pathlib import Path

from engine.chapter_files import chapter_files, parse_chapter_number
from engine.pending import _atomic_write, list_pending


def content_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _managed_files(root):
    paths = [root / name for name in ("config.py", "novel_prompts.json") if (root / name).is_file()]
    for folder, patterns in {
        "bible": ("*.json", "*.md", "outline_parts/**/*.md"),
        "cache": ("keeper_cache_*.json", "archive_plan_*.json", "pipeline_progress.json"),
        "generated": ("chapter_*.md",),
    }.items():
        for pattern in patterns:
            paths.extend((root / folder).glob(pattern))
    return sorted(set(p for p in paths if p.is_file()))


def recover(root):
    from engine.locking import novel_lock
    with novel_lock(root):
        return _recover(root)


def _recover(root):
    root = Path(root).resolve()
    journal = root / "knowledge_transaction.json"
    if not journal.exists():
        return False
    info = json.loads(journal.read_text(encoding="utf-8"))
    backup = (root / info["backup"]).resolve()
    if backup.parent != root / ".history":
        raise ValueError("无效的知识备份路径")
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    saved = {}
    for relative in manifest["files"]:
        target = (root / relative).resolve()
        allowed = target in (root / "config.py", root / "novel_prompts.json") or any(
            target.is_relative_to(root / folder) for folder in ("bible", "cache", "generated"))
        if not allowed:
            raise ValueError("无效的知识恢复目标")
        saved[target] = backup / relative
    for path in _managed_files(root):
        if path not in saved:
            path.unlink()
    for path, source in saved.items():
        _atomic_write(path, source.read_text(encoding="utf-8"))
    db_path = root / "db" / "novel.db"
    if (backup / "novel.db").exists():
        db_path.parent.mkdir(exist_ok=True)
        with closing(sqlite3.connect(backup / "novel.db")) as source, closing(sqlite3.connect(db_path)) as target:
            source.backup(target)
    else:
        for path in (db_path, Path(str(db_path) + "-wal"), Path(str(db_path) + "-shm")):
            path.unlink(missing_ok=True)
    journal.unlink()
    return True


@contextmanager
def transaction(root):
    from engine.locking import novel_lock
    with novel_lock(root), _transaction(root) as backup:
        yield backup


@contextmanager
def _transaction(root):
    root = Path(root).resolve()
    journal = root / "knowledge_transaction.json"
    if journal.exists():
        raise RuntimeError("上次归档中断，请先运行 recover 恢复知识备份")
    backup = root / ".history" / ("knowledge-" + uuid.uuid4().hex)
    previous = sorted((root / ".history").glob("knowledge-*/manifest.json"),
                      key=lambda p: p.stat().st_mtime, reverse=True)
    previous = previous[0].parent if previous else None
    backup.mkdir(parents=True)
    files = _managed_files(root)
    for path in files:
        target = backup / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        prior = previous / path.relative_to(root) if previous else None
        if (prior and prior.is_file() and path.stat().st_size == prior.stat().st_size
                and hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(prior.read_bytes()).digest()):
            try:
                os.link(prior, target)
                continue
            except OSError:
                pass
        shutil.copy2(path, target)
    db_path = root / "db" / "novel.db"
    if db_path.exists():
        with closing(sqlite3.connect(db_path)) as source, closing(sqlite3.connect(backup / "novel.db")) as target:
            source.backup(target)
    _atomic_write(backup / "manifest.json", json.dumps({"files": [p.relative_to(root).as_posix() for p in files]}))
    _atomic_write(journal, json.dumps({"backup": backup.relative_to(root).as_posix()}))
    try:
        yield backup
    except BaseException:
        recover(root)
        raise
    else:
        journal.unlink()


def stale_chapters(config):
    from engine.db import NovelDB
    db = NovelDB(config.bible_dir.parent)
    try:
        stale = {row[0] for row in db.conn.execute(
            "SELECT chapter FROM chapter_log WHERE status='knowledge_stale'")}
        hashes = dict(db.conn.execute("SELECT chapter, content_hash FROM chapter_summaries"))
        for path in chapter_files(config.generated_dir):
            chapter = parse_chapter_number(path)
            expected = hashes.get(chapter)
            if expected and expected != content_hash(path.read_text(encoding="utf-8")):
                stale.add(chapter)
        return sorted(stale)
    finally:
        db.close()


def check_ready(config, chapter, *, publishing=False):
    root = config.bible_dir.parent
    if (root / "knowledge_transaction.json").exists():
        raise ValueError("归档中断，请先恢复知识备份（recover）")
    waiting = [p["num"] for p in list_pending(config)
               if p["num"] < chapter or (p["num"] == chapter and not publishing)]
    if waiting:
        raise ValueError(f"第{min(waiting)}章仍待修订，请先定稿或丢弃")
    existing = {parse_chapter_number(p) for p in chapter_files(config.generated_dir)}
    missing = next((n for n in range(1, chapter) if n not in existing), None)
    if missing:
        raise ValueError(f"前置第{missing}章尚未定稿，不能跳章写作")
    stale = [n for n in stale_chapters(config) if n < chapter or not publishing]
    if stale:
        raise ValueError(f"第{min(stale)}章起知识已过期，请先重建知识（rebuild）")


def ensure_seed(config):
    path = config.bible_dir / "knowledge_seed.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    foundations = config.bible_dir / "character_foundations.json"
    character_path = foundations if foundations.exists() else config.bible_dir / "characters.json"
    characters = json.loads(character_path.read_text(encoding="utf-8")) if character_path.exists() else {"characters": {}}
    if chapter_files(config.generated_dir) and not foundations.exists():
        stable = {"role", "voice_print", "goal", "bottom_line", "expertise", "limits", "immutable_facts", "first_appearance_chapter"}
        characters = {"characters": {name: {k: v for k, v in profile.items() if k in stable}
                                     for name, profile in characters.get("characters", {}).items()}}
    seed = {"characters": characters, "clues": {"clues": {}, "active_foreshadowing": {}}}
    if not chapter_files(config.generated_dir):
        clues = config.bible_dir / "clues.json"
        if clues.exists():
            seed["clues"] = json.loads(clues.read_text(encoding="utf-8"))
    _atomic_write(path, json.dumps(seed, ensure_ascii=False, indent=2))
    return seed


def rebuild(config, *, replacement=None, records=None, _in_transaction=False):
    """Re-extract final manuscripts in order; restore all derivatives on failure."""
    from engine.agents.archivist import ArchivistAgent
    from engine.agents.keeper import KeeperAgent
    from engine.agents.story_keeper import StoryKeeperAgent, record_actual_events
    from engine.db import NovelDB
    from engine.style_kit.scanner import scan

    root = config.bible_dir.parent
    from contextlib import nullcontext
    with nullcontext() if _in_transaction else transaction(root):
        seed = ensure_seed(config)
        # Runtime extraction cannot alter these fields; retain direct author edits too.
        from engine.authoring import STABLE_CHARACTER_FIELDS
        current_path = config.bible_dir / "characters.json"
        current = json.loads(current_path.read_text(encoding="utf-8")) if current_path.exists() else {}
        for name, profile in current.get("characters", {}).items():
            stable = {k: v for k, v in profile.items() if k in STABLE_CHARACTER_FIELDS}
            seed["characters"].setdefault("characters", {}).setdefault(name, {}).update(stable)
        _atomic_write(config.bible_dir / "knowledge_seed.json", json.dumps(seed, ensure_ascii=False, indent=2))
        for name in ("characters", "clues"):
            _atomic_write(config.bible_dir / (name + ".json"), json.dumps(seed[name], ensure_ascii=False, indent=2))
        for name in ("story_state.json", "actual_timeline.md"):
            (config.bible_dir / name).unlink(missing_ok=True)
        keeper, archivist, story = KeeperAgent(), ArchivistAgent(), StoryKeeperAgent()
        keeper.invalidate_from(1)
        db = NovelDB(root, auto_import=False)
        try:
            for table in ("characters", "character_states", "chapter_summaries", "chapter_facts", "clues", "foreshadowing", "style_hits"):
                db.conn.execute(f"DELETE FROM {table}")
            db.conn.execute("UPDATE chapter_log SET status='knowledge_stale'")
            db.conn.commit()
            db.ensure_imported(force=True)
        finally:
            db.close()
        from engine.authoring import apply_edits
        apply_edits(root, 0)
        manuscripts = {parse_chapter_number(p): p.read_text(encoding="utf-8") for p in chapter_files(config.generated_dir)}
        if replacement:
            manuscripts[replacement[0]] = replacement[1]
        for chapter, text in sorted(manuscripts.items()):
            if not text.strip():
                raise ValueError(f"第{chapter}章为空，无法重建")
            plan_path = config.cache_dir / f"archive_plan_{chapter:02d}.json"
            plan = json.loads(plan_path.read_text(encoding="utf-8")) if plan_path.exists() else {"chapter_title": f"第{chapter}章"}
            if replacement and chapter == replacement[0]:
                plan = replacement[2]
            record = (records or {}).get(str(chapter))
            if record is not None:
                if record.get("source_hash") != content_hash(text):
                    raise ValueError(f"第{chapter}章人工归档与正文版本不一致")
                snapshot = dict(record["snapshot"], chapter_num=chapter, scene_id="final", source_hash=content_hash(text))
                if not snapshot.get("plot_progress"):
                    raise ValueError("人工归档缺少剧情摘要")
                cache = keeper.init_cache(chapter)
                cache.update(source_hash=content_hash(text), current_chapter_snapshots=[snapshot],
                             running_context=keeper._build_running_context(cache.get("carry_context", []), [snapshot]))
                plan = record["plan"]
            else:
                cache = keeper.reconcile_final_chapter(keeper.init_cache(chapter), text, chapter)
            cache["_style_hits"] = scan(text).to_rows(chapter)
            kwargs = {"extraction": record["archive"]} if record is not None else {}
            if not archivist.update_bible(chapter, plan, cache, text, **kwargs):
                raise RuntimeError(f"第{chapter}章重建归档失败")
            kwargs = {"extraction": record["story"]} if record is not None else {}
            story.update_state(config.bible_dir, chapter, plan, cache, text, **kwargs)
            record_actual_events(config, chapter, plan, cache)
            keeper.save_cache(chapter, cache)
            _atomic_write(plan_path, json.dumps(plan, ensure_ascii=False, indent=2))
            db = NovelDB(root)
            try:
                db.log_chapter(chapter, title=plan.get("chapter_title", ""), words=len(text), status="generated")
            finally:
                db.close()
        if replacement:
            archivist.save_chapter(replacement[0], replacement[1])
    return len(manuscripts)
