# Archivist Agent — 归档与知识库更新

import json
import logging
from engine.proxy import config

log = logging.getLogger("archivist")


class ArchivistAgent:

    def __init__(self):
        self.model_config = config.archivist_model
        self.generated_dir = config.generated_dir
        self.bible_dir = config.bible_dir

    def _db(self):
        from engine.db import NovelDB
        try:
            return NovelDB(self.bible_dir.parent)
        except Exception as e:
            log.warning(f"DB 不可用，跳过双写: {e}")
            return None

    def save_chapter(self, chapter_num: int, full_chapter: str):
        out_file = self.generated_dir / f"chapter_{chapter_num:02d}.md"
        out_file.write_text(full_chapter, encoding="utf-8")
        log.info(f"章节保存: {out_file}")

    def update_bible(self, chapter_num: int, plan_json: dict,
                     keeper_cache: dict):
        from engine.llm_client import chat_json
        from engine.prompts_loader import get_prompt
        system, _ = get_prompt("archivist")

        prompt = json.dumps({
            "chapter_num": chapter_num,
            "plan_title": plan_json.get("chapter_title", ""),
            "clue_operations": plan_json.get("clue_operations", []),
            "snapshots": keeper_cache.get("snapshots", []),
        }, ensure_ascii=False, indent=2)

        extracted = {}
        try:
            extracted = chat_json(self.model_config,
                                  system_prompt=system,
                                  user_prompt=prompt)
            keeper_cache["character_delta"] = extracted.get(
                "character_updates", {})
            keeper_cache["clue_delta"] = extracted.get("clue_updates", {})
        except Exception as e:
            log.warning(f"Archivist LLM 提取失败: {e}")
            keeper_cache["character_delta"] = {}
            keeper_cache["clue_delta"] = {}

        self._update_characters(chapter_num, keeper_cache)
        self._update_clues(chapter_num, keeper_cache)
        self._update_master_bible(chapter_num, plan_json)
        self._update_foreshadowing(chapter_num, plan_json)
        self._sync_db(chapter_num, keeper_cache, extracted,
                      plan_json.get("clue_operations", []))

    def _sync_db(self, chapter_num: int, keeper_cache: dict, extracted: dict,
                 plan_ops: list):
        """SQLite 双写：人物状态时间线 + 原子事实 + 伏笔操作 + 风格命中 + 章节日志。"""
        db = self._db()
        if not db:
            return
        try:
            for name, state in (keeper_cache.get("character_delta") or {}).items():
                db.add_character_state(chapter_num, name, state)
            facts = extracted.get("facts", []) if isinstance(extracted, dict) else []
            if facts:
                db.add_facts(chapter_num, facts)
            for op in plan_ops:
                fid = (op or {}).get("clue_id")
                if not fid:
                    continue
                act = op.get("action", "")
                if act == "hint":
                    db.hint_foreshadow(fid, chapter_num)
                elif act == "reveal":
                    db.resolve_foreshadow(fid, chapter_num)
            hits = keeper_cache.get("_style_hits", [])
            if hits:
                db.add_style_hits(hits)
            db.conn.commit()
        except Exception as e:
            log.warning(f"DB 双写异常: {e}")
        finally:
            db.close()

    def _update_characters(self, chapter_num: int, keeper_cache: dict):
        characters_file = self.bible_dir / "characters.json"
        if not characters_file.exists():
            return

        chars = json.loads(characters_file.read_text(encoding="utf-8"))
        keeper_chars = keeper_cache.get("character_delta", {})
        if not keeper_chars:
            keeper_chars = keeper_cache.get("characters", {})
        if keeper_chars:
            for name, state in keeper_chars.items():
                if name not in chars.setdefault("characters", {}):
                    chars["characters"][name] = {}
                chars["characters"][name].update(state)
            characters_file.write_text(
                json.dumps(chars, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            log.info(f"characters.json 已更新 (第 {chapter_num} 章)")

    def _update_clues(self, chapter_num: int, keeper_cache: dict):
        clues_file = self.bible_dir / "clues.json"
        if not clues_file.exists():
            return

        clues = json.loads(clues_file.read_text(encoding="utf-8"))
        keeper_clues = keeper_cache.get("clue_delta", {})
        if not keeper_clues:
            keeper_clues = keeper_cache.get("clues", {})
        if keeper_clues:
            for clue_id, state in keeper_clues.items():
                if clue_id not in clues.setdefault("clues", {}):
                    clues["clues"][clue_id] = {}
                clues["clues"][clue_id].update(state)
            clues_file.write_text(
                json.dumps(clues, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            log.info(f"clues.json 已更新 (第 {chapter_num} 章)")

    def _update_foreshadowing(self, chapter_num: int, plan_json: dict):
        clues_file = self.bible_dir / "clues.json"
        if not clues_file.exists():
            return

        clues = json.loads(clues_file.read_text(encoding="utf-8"))
        ops = plan_json.get("clue_operations", [])
        foreshadowing = clues.setdefault("active_foreshadowing", {})
        changed = False
        for op in ops:
            fid = op.get("clue_id", "")
            if fid in foreshadowing:
                action = op.get("action", "")
                if action == "reveal":
                    foreshadowing[fid]["status"] = "resolved"
                    changed = True
                elif action == "hint":
                    foreshadowing[fid]["last_hinted_chapter"] = chapter_num
                    changed = True
        if changed:
            clues_file.write_text(
                json.dumps(clues, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _update_master_bible(self, chapter_num: int, plan_json: dict):
        bible_file = self.bible_dir / "master_bible.md"
        if not bible_file.exists():
            return

        title = plan_json.get("chapter_title", f"第 {chapter_num} 章")
        content = bible_file.read_text(encoding="utf-8")

        entry = f"| {chapter_num} | {title} | generated/chapter_{chapter_num:02d}.md |"
        existing_entries = set()
        for line in content.split("\n"):
            if line.startswith(f"| {chapter_num} |"):
                return

        if "## 章节索引" in content:
            content = content.rstrip() + "\n" + entry + "\n"
            bible_file.write_text(content, encoding="utf-8")
