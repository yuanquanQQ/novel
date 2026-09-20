"""Prepare stable character intentions and voices before drafting."""
import json

from engine.pending import _atomic_write


def prepare(config):
    from engine.llm_client import chat_json
    from engine.prompts_loader import get_prompt
    from engine.knowledge import transaction

    path = config.bible_dir / "characters.json"
    current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"characters": {}}
    master = (config.bible_dir / "master_bible.md").read_text(encoding="utf-8")
    system, _ = get_prompt("foundation")
    result = chat_json(config.planner_model, system_prompt=system,
                       user_prompt=master + "\n已有档案（只补缺项）：\n" + json.dumps(current, ensure_ascii=False))
    chars = result.get("characters") if isinstance(result, dict) else None
    required = ("goal", "bottom_line", "expertise", "limits", "voice_print", "immutable_facts")
    if not isinstance(chars, dict) or not chars or any(
            not isinstance(profile, dict) or any(not profile.get(key) for key in required)
            for profile in chars.values()):
        raise ValueError("人物基础档案不完整，未写入")
    for name, profile in chars.items():
        existing = current.setdefault("characters", {}).setdefault(name, {})
        for key, value in profile.items():
            if not existing.get(key):
                existing[key] = value
    with transaction(config.bible_dir.parent):
        _atomic_write(path, json.dumps(current, ensure_ascii=False, indent=2))
        foundations = {"characters": {name: {k: v for k, v in profile.items()
                        if k in required + ("role", "first_appearance_chapter",)}
                        for name, profile in current["characters"].items()}}
        _atomic_write(config.bible_dir / "character_foundations.json", json.dumps(foundations, ensure_ascii=False, indent=2))
        seed_path = config.bible_dir / "knowledge_seed.json"
        if seed_path.exists():
            seed = json.loads(seed_path.read_text(encoding="utf-8"))
            seed["characters"] = foundations
            _atomic_write(seed_path, json.dumps(seed, ensure_ascii=False, indent=2))
    return len(chars)
