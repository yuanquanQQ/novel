# Continuity Keeper — 连续性守护者 / 记忆压缩器

import hashlib
import json
import logging
from engine.proxy import config

log = logging.getLogger("keeper")

SNAPSHOT_WINDOW = 5


class KeeperAgent:

    def __init__(self):
        self.model_config = config.keeper_model
        self.cache_dir = config.cache_dir

    def init_cache(self, chapter_num: int) -> dict:
        prev_cache = self._load_cache(chapter_num - 1)
        carry = (
            prev_cache.get("current_chapter_snapshots")
            or prev_cache.get("snapshots", [])
        )[-SNAPSHOT_WINDOW:]
        carry = [self._normalize_snapshot(s, chapter_num - 1) for s in carry]
        cache = {
            "chapter": chapter_num,
            "carry_context": carry,
            "current_chapter_snapshots": [],
            "all_scenes": [],
            "scene_count": 0,
            "running_context": self._build_running_context(carry, []),
            "characters": prev_cache.get("characters", {}),
            "clues": prev_cache.get("clues", {}),
        }
        log.info(f"Keeper — 初始化第 {chapter_num} 章缓存 "
                 f"(继承 {len(carry)} 个快照)")
        return cache

    def update(self, keeper_cache: dict, draft: str, chapter_num: int,
               scene_id: int) -> dict:
        log.info(f"Keeper — 场景 {scene_id} 压缩")
        keeper_cache.setdefault("all_scenes", []).append(draft)
        keeper_cache["scene_count"] = len(keeper_cache["all_scenes"])
        snapshot = self._compress_scene(draft, chapter_num, scene_id)
        keeper_cache.setdefault("current_chapter_snapshots", []).append(snapshot)
        keeper_cache["running_context"] = self._build_running_context(
            keeper_cache.get("carry_context", []),
            keeper_cache["current_chapter_snapshots"],
        )
        return keeper_cache

    def _compress_scene(self, draft: str, chapter_num: int, scene_id: int) -> dict:
        from engine.prompts_loader import get_prompt
        system, _ = get_prompt("keeper")
        prompt = system.format(scene_draft=draft, scene_id=scene_id)
        result = self._call_llm(prompt)
        result.update({
            "chapter_num": chapter_num,
            "scene_id": scene_id,
            "source_hash": hashlib.sha256(draft.encode("utf-8")).hexdigest(),
        })
        return result

    def _normalize_snapshot(self, snapshot: dict, chapter_num: int) -> dict:
        normalized = dict(snapshot) if isinstance(snapshot, dict) else {}
        normalized.setdefault("chapter_num", chapter_num)
        normalized.setdefault("scene_id", 0)
        normalized.setdefault("source_hash", "")
        return normalized

    def _build_running_context(self, carry: list, current: list | None = None) -> str:
        snapshots = list(carry) if current is None else list(carry) + list(current)
        lines = []
        for i, s in enumerate(snapshots[-SNAPSHOT_WINDOW:], 1):
            lines.append(
                f"[第{s.get('chapter_num', '?')}章 场景{s.get('scene_id', i)}] "
                f"剧情: {s.get('plot_progress', '')} | "
                f"情绪: {s.get('emotion_state', '')} | "
                f"环境/伏笔: {s.get('env_and_clue', '')}"
            )
        return "\n".join(lines)

    def _call_llm(self, prompt: str) -> dict:
        from engine.llm_client import chat_json
        return chat_json(self.model_config, user_prompt=prompt)

    def save_cache(self, chapter_num: int, keeper_cache: dict):
        cache_file = self.cache_dir / f"keeper_cache_{chapter_num:02d}.json"
        current = keeper_cache.get("current_chapter_snapshots", [])
        save_data = {
            "chapter": keeper_cache.get("chapter", chapter_num),
            "carry_context": keeper_cache.get("carry_context", []),
            "current_chapter_snapshots": current,
            "snapshots": current,
            "scene_count": keeper_cache.get("scene_count", 0),
            "running_context": keeper_cache.get("running_context", ""),
            "characters": keeper_cache.get("characters", {}),
            "clues": keeper_cache.get("clues", {}),
        }
        cache_file.write_text(
            json.dumps(save_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log.info(f"Keeper 缓存已保存: {cache_file}")

    def invalidate_from(self, chapter_num: int) -> int:
        removed = 0
        for cache_file in self.cache_dir.glob("keeper_cache_*.json"):
            try:
                cached_chapter = int(cache_file.stem.rsplit("_", 1)[-1])
            except ValueError:
                continue
            if cached_chapter >= chapter_num:
                cache_file.unlink()
                removed += 1
        return removed

    def _load_cache(self, chapter_num: int) -> dict:
        cache_file = self.cache_dir / f"keeper_cache_{chapter_num:02d}.json"
        if cache_file.exists():
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            if "current_chapter_snapshots" not in data:
                data["current_chapter_snapshots"] = [
                    self._normalize_snapshot(s, data.get("chapter", chapter_num))
                    for s in data.get("snapshots", [])
                ]
            data.setdefault("carry_context", [])
            return data
        return {"current_chapter_snapshots": [], "snapshots": [],
                "scene_count": 0, "characters": {}, "clues": {}}
