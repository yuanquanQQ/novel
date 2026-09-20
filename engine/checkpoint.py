"""Resume completed scenes only while all writing inputs still match."""
import hashlib
import json
from pathlib import Path

from engine.chapter_files import chapter_files
from engine.pending import _atomic_write


def checkpoint_path(config, chapter, instruction, title):
    digest = hashlib.sha256()
    options = {"chapter": chapter, "instruction": instruction, "title": title}
    for key in ("words_per_chapter", "immediate_review_max_retries", "chapter_edit_max_retries",
                "heavy_review_interval", "gate_fail_mode", "base_url"):
        options[key] = getattr(config, key, None)
    for role in ("planner", "writer", "researcher", "keeper", "immediate_reviewer", "heavy_reviewer",
                 "story_keeper", "reader_proxy", "foreshadowing_steward", "archivist"):
        model = getattr(config, role + "_model", None)
        options[role] = {key: getattr(model, key, None) for key in ("model_name", "temperature", "max_tokens", "top_p")}
    digest.update(json.dumps(options, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    engine = Path(__file__).resolve().parent
    files = [*config.bible_dir.rglob("*.json"), *config.bible_dir.rglob("*.md"),
             *config.bible_dir.glob("*.jsonl"), *chapter_files(config.generated_dir, before_chapter=chapter),
             config.bible_dir.parent / "novel_prompts.json", config.bible_dir.parent / "config.py",
             config.cache_dir / f"keeper_cache_{chapter - 1:02d}.json",
             *config.cache_dir.glob("archive_plan_*.json"), engine.parent / "novel.py", *engine.glob("*.py"),
             *engine.joinpath("agents").glob("*.py"), *engine.joinpath("style_kit").glob("*")]
    for path in sorted(set(files)):
        if path.is_file():
            digest.update(str(path).encode("utf-8"))
            digest.update(path.read_bytes())
    return config.cache_dir / f"draft_checkpoint_{chapter:02d}_{digest.hexdigest()[:20]}.json"


def load(path):
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or not isinstance(data.get("plan"), dict) or not isinstance(data.get("keeper_cache"), dict)
            or type(data.get("completed")) is not int or data["completed"] < 0
            or not isinstance(data.get("scene_failures"), list)):
        raise ValueError("写作检查点格式损坏，请保留该文件后检查，不自动覆盖")
    scenes = data["plan"].get("scene_outline")
    drafts = data["keeper_cache"].get("all_scenes")
    snapshots = data["keeper_cache"].get("current_chapter_snapshots", [])
    if (not isinstance(scenes, list) or not isinstance(drafts, list) or not isinstance(snapshots, list)
            or not 0 <= data["completed"] <= len(scenes)
            or len(drafts) != data["completed"] or len(snapshots) != data["completed"]
            or any(not isinstance(draft, str) or not draft.strip() for draft in drafts)):
        raise ValueError("写作检查点的正文、摘要与场景进度不一致，不自动续写")
    return data


def save(path, plan, cache, completed, failures):
    _atomic_write(path, json.dumps({"plan": plan, "keeper_cache": cache,
        "completed": completed, "scene_failures": failures}, ensure_ascii=False, indent=2))
