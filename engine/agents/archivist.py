# Archivist Agent — 归档与知识库更新

import hashlib
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
                     keeper_cache: dict, full_chapter: str) -> bool:
        from engine.llm_client import chat_json
        from engine.prompts_loader import get_prompt
        system, _ = get_prompt("archivist")
        snapshots = keeper_cache.get("current_chapter_snapshots", [])
        if any(s.get("chapter_num") != chapter_num for s in snapshots):
            raise ValueError("Archivist 收到非当前章快照")
        prompt = json.dumps({
            "chapter_num": chapter_num,
            "plan_title": plan_json.get("chapter_title", ""),
            "clue_operations": plan_json.get("clue_operations", []),
            "current_chapter_snapshots": snapshots,
            "full_chapter": full_chapter,
        }, ensure_ascii=False, indent=2)
        try:
            extracted = chat_json(self.model_config, system_prompt=system,
                                  user_prompt=prompt)
            if not isinstance(extracted, dict) or not extracted.get("chapter_summary"):
                raise ValueError("Archivist 返回缺少 chapter_summary")
            keeper_cache["character_delta"] = extracted.get("character_updates", {})
            keeper_cache["clue_delta"] = extracted.get("clue_updates", {})
            self._sync_db(chapter_num, keeper_cache, extracted,
                          plan_json.get("clue_operations", []), full_chapter)
        except Exception as e:
            log.error(f"Archivist 归档失败: {e}")
            return False
        self._update_characters(chapter_num, keeper_cache)
        self._update_clues(chapter_num, keeper_cache)
        self._update_master_bible(chapter_num, plan_json)
        self._update_foreshadowing(chapter_num, plan_json)
        return True

    def _sync_db(self, chapter_num: int, keeper_cache: dict, extracted: dict,
                 plan_ops: list, full_chapter: str):
        db = self._db()
        if not db:
            raise RuntimeError("知识库不可用")
        try:
            db.replace_chapter_derivatives(
                chapter_num, extracted.get("facts", []),
                keeper_cache.get("character_delta") or {},
                extracted["chapter_summary"],
                hashlib.sha256(full_chapter.encode("utf-8")).hexdigest(),
            )
            for op in plan_ops:
                fid = (op or {}).get("clue_id")
                action = (op or {}).get("action")
                if not fid:
                    raise ValueError("伏笔操作缺少 clue_id")
                if action == "plant":
                    data = dict(op)
                    data.setdefault("introduced_chapter", chapter_num)
                    changed = db.create_foreshadow(fid, data)
                elif action == "hint":
                    changed = db.hint_foreshadow(fid, chapter_num)
                elif action == "escalate":
                    changed = db.hint_foreshadow(fid, chapter_num, status="escalated")
                elif action == "reveal":
                    changed = db.resolve_foreshadow(fid, chapter_num)
                elif action == "reschedule":
                    changed = db.reschedule_foreshadow(fid, op)
                elif action == "retire":
                    changed = db.retire_foreshadow(fid, chapter_num)
                else:
                    raise ValueError(f"未知伏笔操作: {action}")
                if changed != 1:
                    raise ValueError(f"伏笔操作未命中唯一记录: {action} {fid}")
            hits = keeper_cache.get("_style_hits", [])
            db.delete_style_hits(chapter_num)
            if hits:
                db.add_style_hits(hits)
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
            action = op.get("action", "")
            if action == "plant":
                if fid in foreshadowing:
                    raise ValueError(f"重复 plant 已存在伏笔 {fid}")
                foreshadowing[fid] = {
                    "name": op.get("name", ""),
                    "description": op.get("description", ""),
                    "status": "pending",
                    "introduced_chapter": op.get("introduced_chapter", chapter_num),
                    "intended_payoff_chapter": op.get("intended_payoff_chapter"),
                    "payoff_start_chapter": op.get("payoff_start_chapter"),
                    "payoff_end_chapter": op.get("payoff_end_chapter"),
                    "scope": op.get("scope"),
                    "importance": op.get("importance"),
                    "touch_interval": op.get("touch_interval"),
                    "hinted_chapters": [chapter_num],
                }
                changed = True
                continue
            if fid not in foreshadowing:
                raise ValueError(f"{action} 指向未知伏笔 {fid}")
            item = foreshadowing[fid]
            if action in ("hint", "escalate"):
                timeline = item.setdefault("hinted_chapters", [])
                if chapter_num not in timeline:
                    timeline.append(chapter_num)
                item["last_hinted_chapter"] = chapter_num
                if action == "escalate":
                    item["status"] = "escalated"
            elif action == "reveal":
                item["status"] = "resolved"
                item["resolved_chapter"] = chapter_num
            elif action == "retire":
                item["status"] = "retired"
                item["resolved_chapter"] = chapter_num
            elif action == "reschedule":
                for field in ("intended_payoff_chapter", "payoff_start_chapter",
                              "payoff_end_chapter", "touch_interval"):
                    if op.get(field) is not None:
                        item[field] = op[field]
            else:
                raise ValueError(f"未知伏笔操作: {action}")
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
