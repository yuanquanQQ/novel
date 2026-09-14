# Continuity Keeper — 连续性守护者 / 记忆压缩器

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
        prev_snapshots = prev_cache.get("snapshots", [])
        cache = {
            "chapter": chapter_num,
            "snapshots": prev_snapshots[-SNAPSHOT_WINDOW:] if prev_snapshots else [],
            "all_scenes": [],
            "scene_count": 0,
            "running_context": "",
            "characters": prev_cache.get("characters", {}),
            "clues": prev_cache.get("clues", {}),
        }
        if cache["snapshots"]:
            cache["running_context"] = self._build_running_context(
                cache["snapshots"]
            )
        log.info(f"Keeper — 初始化第 {chapter_num} 章缓存 "
                 f"(继承 {len(cache['snapshots'])} 个快照)")
        return cache

    def update(self, keeper_cache: dict, draft: str, chapter_num: int,
               scene_id: int) -> dict:
        log.info(f"Keeper — 场景 {scene_id} 压缩")

        keeper_cache.setdefault("all_scenes", []).append(draft)
        keeper_cache["scene_count"] = len(keeper_cache["all_scenes"])

        snapshot = self._compress_scene(draft, scene_id)
        keeper_cache.setdefault("snapshots", []).append(snapshot)
        keeper_cache["running_context"] = self._build_running_context(
            keeper_cache["snapshots"]
        )
        return keeper_cache

    def _compress_scene(self, draft: str, scene_id: int) -> dict:
        from engine.prompts_loader import get_prompt
        system, _ = get_prompt("keeper")
        prompt = system.format(
            scene_draft=draft,
            scene_id=scene_id,
        )
        result = self._call_llm(prompt)
        result["scene_id"] = scene_id
        return result

    def _build_running_context(self, snapshots: list) -> str:
        lines = []
        for i, s in enumerate(snapshots[-SNAPSHOT_WINDOW:], 1):
            lines.append(
                f"[场景 {s.get('scene_id', i)}] "
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
        save_data = {
            "chapter": keeper_cache.get("chapter"),
            "snapshots": keeper_cache.get("snapshots", []),
            "scene_count": keeper_cache.get("scene_count", 0),
            "running_context": keeper_cache.get("running_context", ""),
            "characters": keeper_cache.get("characters", {}),
            "clues": keeper_cache.get("clues", {}),
        }
        cache_file.write_text(
            json.dumps(save_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info(f"Keeper 缓存已保存: {cache_file}")

    def _load_cache(self, chapter_num: int) -> dict:
        cache_file = self.cache_dir / f"keeper_cache_{chapter_num:02d}.json"
        if cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8"))
        return {"snapshots": [], "scene_count": 0,
                "characters": {}, "clues": {}}
