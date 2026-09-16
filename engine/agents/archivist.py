# Archivist Agent — 归档与知识库更新

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path

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
        except Exception as exc:
            log.warning(f"DB 不可用，跳过双写: {exc}")
            return None

    @staticmethod
    def _atomic_write(path: Path, content: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=path.parent,
                prefix=path.name + ".", suffix=".tmp", delete=False,
            ) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
                temp_name = handle.name
            os.replace(temp_name, path)
            temp_name = None
        finally:
            if temp_name:
                Path(temp_name).unlink(missing_ok=True)

    def save_chapter(self, chapter_num: int, full_chapter: str):
        out_file = self.generated_dir / f"chapter_{chapter_num:02d}.md"
        self._atomic_write(out_file, full_chapter)
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
            extracted = chat_json(
                self.model_config, system_prompt=system, user_prompt=prompt,
            )
            if not isinstance(extracted, dict) or not extracted.get("chapter_summary"):
                raise ValueError("Archivist 返回缺少 chapter_summary")
            keeper_cache["character_delta"] = extracted.get("character_updates", {})
            keeper_cache["clue_delta"] = extracted.get("clue_updates", {})
            updates = self._prepare_file_updates(chapter_num, plan_json, keeper_cache)
            self._commit_archive(
                chapter_num, keeper_cache, extracted,
                plan_json.get("clue_operations", []), full_chapter, updates,
            )
        except Exception as exc:
            log.error(f"Archivist 归档失败: {exc}")
            return False
        return True

    def _prepare_file_updates(self, chapter_num: int, plan_json: dict,
                              keeper_cache: dict) -> dict[Path, str]:
        updates = {}
        characters_file = self.bible_dir / "characters.json"
        if characters_file.exists():
            chars = json.loads(characters_file.read_text(encoding="utf-8"))
            delta = (keeper_cache.get("character_delta")
                     or keeper_cache.get("characters", {}))
            for name, state in delta.items():
                chars.setdefault("characters", {}).setdefault(name, {}).update(state)
            if delta:
                updates[characters_file] = json.dumps(chars, ensure_ascii=False, indent=2)

        clues_file = self.bible_dir / "clues.json"
        if clues_file.exists():
            clues = json.loads(clues_file.read_text(encoding="utf-8"))
            delta = keeper_cache.get("clue_delta") or keeper_cache.get("clues", {})
            for clue_id, state in delta.items():
                clues.setdefault("clues", {}).setdefault(clue_id, {}).update(state)
            self._apply_foreshadowing_json(
                clues, chapter_num, plan_json.get("clue_operations", []),
            )
            if delta or plan_json.get("clue_operations"):
                updates[clues_file] = json.dumps(clues, ensure_ascii=False, indent=2)

        bible_file = self.bible_dir / "master_bible.md"
        if bible_file.exists():
            content = bible_file.read_text(encoding="utf-8")
            if not any(line.startswith(f"| {chapter_num} |")
                       for line in content.splitlines()):
                title = plan_json.get("chapter_title", f"第 {chapter_num} 章")
                entry = (f"| {chapter_num} | {title} | "
                         f"generated/chapter_{chapter_num:02d}.md |")
                if "## 章节索引" in content:
                    updates[bible_file] = content.rstrip() + "\n" + entry + "\n"
        return updates

    def _commit_archive(self, chapter_num: int, keeper_cache: dict,
                        extracted: dict, plan_ops: list, full_chapter: str,
                        updates: dict[Path, str]):
        db = self._db()
        if not db:
            raise RuntimeError("知识库不可用")
        originals = {
            path: path.read_text(encoding="utf-8") if path.exists() else None
            for path in updates
        }
        try:
            db.conn.execute("BEGIN IMMEDIATE")
            self._sync_db(
                chapter_num, keeper_cache, extracted, plan_ops, full_chapter,
                db=db, commit=False,
            )
            for path, content in updates.items():
                self._atomic_write(path, content)
            db.conn.commit()
        except Exception:
            db.conn.rollback()
            for path, content in originals.items():
                try:
                    if content is None:
                        path.unlink(missing_ok=True)
                    else:
                        self._atomic_write(path, content)
                except OSError as restore_error:
                    log.critical(f"归档回滚文件失败 {path}: {restore_error}")
            raise
        finally:
            db.close()

    def _sync_db(self, chapter_num: int, keeper_cache: dict, extracted: dict,
                 plan_ops: list, full_chapter: str, db=None, commit=True):
        owned = db is None
        db = db or self._db()
        if not db:
            raise RuntimeError("知识库不可用")
        try:
            if commit:
                db.conn.execute("BEGIN IMMEDIATE")
            db.replace_chapter_derivatives(
                chapter_num, extracted.get("facts", []),
                keeper_cache.get("character_delta") or {},
                extracted["chapter_summary"],
                hashlib.sha256(full_chapter.encode("utf-8")).hexdigest(),
                commit=False,
            )
            for op in plan_ops:
                fid = (op or {}).get("clue_id")
                action = (op or {}).get("action")
                if not fid:
                    raise ValueError("伏笔操作缺少 clue_id")
                if action == "plant":
                    data = dict(op)
                    data.setdefault("introduced_chapter", chapter_num)
                    changed = db.create_foreshadow(fid, data, commit=False)
                elif action == "hint":
                    changed = db.hint_foreshadow(fid, chapter_num, commit=False)
                elif action == "escalate":
                    changed = db.hint_foreshadow(
                        fid, chapter_num, status="escalated", commit=False,
                    )
                elif action == "reveal":
                    changed = db.resolve_foreshadow(fid, chapter_num, commit=False)
                elif action == "reschedule":
                    changed = db.reschedule_foreshadow(fid, op, commit=False)
                elif action == "retire":
                    changed = db.retire_foreshadow(fid, chapter_num, commit=False)
                else:
                    raise ValueError(f"未知伏笔操作: {action}")
                if changed != 1:
                    raise ValueError(f"伏笔操作未命中唯一记录: {action} {fid}")
            hits = keeper_cache.get("_style_hits", [])
            db.delete_style_hits(chapter_num, commit=False)
            if hits:
                db.add_style_hits(hits, commit=False)
            if commit:
                db.conn.commit()
        except Exception:
            if commit:
                db.conn.rollback()
            raise
        finally:
            if owned:
                db.close()

    @staticmethod
    def _apply_foreshadowing_json(clues: dict, chapter_num: int, ops: list):
        foreshadowing = clues.setdefault("active_foreshadowing", {})
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
                for field in (
                    "intended_payoff_chapter", "payoff_start_chapter",
                    "payoff_end_chapter", "touch_interval",
                ):
                    if op.get(field) is not None:
                        item[field] = op[field]
            else:
                raise ValueError(f"未知伏笔操作: {action}")

    def _update_characters(self, chapter_num: int, keeper_cache: dict):
        updates = self._prepare_file_updates(chapter_num, {}, keeper_cache)
        path = self.bible_dir / "characters.json"
        if path in updates:
            self._atomic_write(path, updates[path])

    def _update_clues(self, chapter_num: int, keeper_cache: dict):
        updates = self._prepare_file_updates(chapter_num, {}, keeper_cache)
        path = self.bible_dir / "clues.json"
        if path in updates:
            self._atomic_write(path, updates[path])

    def _update_foreshadowing(self, chapter_num: int, plan_json: dict):
        updates = self._prepare_file_updates(chapter_num, plan_json, {})
        path = self.bible_dir / "clues.json"
        if path in updates:
            self._atomic_write(path, updates[path])

    def _update_master_bible(self, chapter_num: int, plan_json: dict):
        updates = self._prepare_file_updates(chapter_num, plan_json, {})
        path = self.bible_dir / "master_bible.md"
        if path in updates:
            self._atomic_write(path, updates[path])
