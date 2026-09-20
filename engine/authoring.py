"""Record author edits separately from inferred knowledge and replay them on rebuild."""
import json

from engine.chapter_files import chapter_files, parse_chapter_number
from engine.pending import _atomic_write

STABLE_CHARACTER_FIELDS = {
    "role", "goal", "voice_print", "bottom_line", "expertise", "limits",
    "immutable_facts", "first_appearance_chapter",
}


def record_edit(root, filename, before, after, chapter=None):
    buckets = {"characters.json": ("characters",),
               "clues.json": ("clues", "active_foreshadowing")}.get(filename, ())
    if not buckets:
        return
    path = root / "bible/author_overrides.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"records": []}
    at = chapter if chapter is not None else max(
        (parse_chapter_number(p) for p in chapter_files(root / "generated")), default=0)
    for bucket in buckets:
        old, new = before.get(bucket, {}), after.get(bucket, {})
        for name in old.keys() | new.keys():
            if name not in new:
                data["records"].append({"bucket": bucket, "id": name, "chapter": at, "delete": True})
                continue
            prior, current = old.get(name, {}), new[name]
            changed = {k: v for k, v in current.items() if k not in prior or prior[k] != v}
            removed = list(prior.keys() - current.keys())
            # Stable identity applies throughout; runtime corrections belong to a chapter.
            stable = STABLE_CHARACTER_FIELDS if bucket == "characters" else set()
            for permanent in (True, False):
                values = {k: v for k, v in changed.items() if (k in stable) == permanent}
                deletes = [k for k in removed if (k in stable) == permanent]
                if values or deletes:
                    data["records"].append({"bucket": bucket, "id": name,
                        "chapter": 0 if permanent else at, "permanent": permanent,
                        "set": values, "remove": deletes})
    _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2))


def _selected_records(root, chapter):
    path = root / "bible/author_overrides.json"
    if not path.exists():
        return []
    records = json.loads(path.read_text(encoding="utf-8"))["records"]
    return [r for r in records if r.get("permanent", False) or r["chapter"] == chapter
            or (r.get("delete") and r["chapter"] <= chapter)]


def overlay_story(root, chapter, state):
    """Keep author corrections authoritative in the story ledger as well."""
    aliases = {
        "location": ("位置", "所在地", "所在位置", "地点"),
        "status": ("状态",), "goal": ("目标",), "relationships": ("关系", "人物关系"),
        "health": ("健康", "伤势"),
    }
    for record in _selected_records(root, chapter):
        if record["bucket"] != "characters":
            continue
        name = record["id"]
        facts = state.setdefault("facts", {})
        arcs = state.setdefault("character_arcs", {})
        if record.get("delete"):
            facts.pop(name, None)
            arcs.pop(name, None)
            continue
        bucket = facts.setdefault(name, {})
        touched = set()
        for key in record.get("set", {}).keys() | set(record.get("remove", [])):
            keys = {key, *aliases.get(key, ())}
            for canonical, names in aliases.items():
                if key in names:
                    keys.update((canonical, *names))
            targets = keys.intersection(bucket) or {aliases.get(key, (key,))[0]}
            touched.update(keys)
            for attr in targets:
                if key in record.get("set", {}):
                    bucket[attr] = {"value": record["set"][key], "chapters": [record["chapter"]],
                                    "source": "author"}
                else:
                    bucket.pop(attr, None)
            if key in ("goal", "fear", "secret", "conflict", "change"):
                arc = arcs.setdefault(name, {})
                if key in record.get("set", {}):
                    arc[key] = record["set"][key]
                else:
                    arc.pop(key, None)
        state["continuity_warnings"] = [w for w in state.get("continuity_warnings", [])
            if not (w.get("entity") == name and w.get("attribute") in touched)]


def apply_edits(root, chapter):
    selected = _selected_records(root, chapter)
    if not selected:
        return
    from engine.db import NovelDB
    documents = {}
    changed = set()
    for record in selected:
        bucket, name = record["bucket"], record["id"]
        filename = "characters.json" if bucket == "characters" else "clues.json"
        if filename not in documents:
            documents[filename] = json.loads((root / "bible" / filename).read_text(encoding="utf-8"))
        items = documents[filename].setdefault(bucket, {})
        if record.get("delete"):
            items.pop(name, None)
        else:
            profile = items.setdefault(name, {})
            profile.update(record.get("set", {}))
            for key in record.get("remove", []):
                profile.pop(key, None)
        changed.add((filename, bucket, name))
    db = NovelDB(root, auto_import=False)
    try:
        with db.conn:
            for filename, bucket, name in changed:
                profile = documents[filename][bucket].get(name)
                if profile is None:
                    table, key = {"characters": ("characters", "name"), "clues": ("clues", "id"),
                                  "active_foreshadowing": ("foreshadowing", "id")}[bucket]
                    db.conn.execute(f"DELETE FROM {table} WHERE {key}=?", (name,))
                    if bucket == "characters":
                        db.conn.execute("DELETE FROM character_states WHERE character=? AND chapter>=?", (name, chapter))
                elif bucket == "characters":
                    db.upsert_character(name, profile, commit=False)
                    db.conn.execute(
                        "INSERT INTO character_states(chapter,character,state_json) VALUES(?,?,?) "
                        "ON CONFLICT(chapter,character) DO UPDATE SET state_json=excluded.state_json",
                        (chapter, name, json.dumps(profile, ensure_ascii=False)))
                elif bucket == "clues":
                    metadata = {"name", "type", "description", "introduced_chapter",
                                "intended_reveal_chapter", "intended_resolution_chapter", "resolved"}
                    clue = dict(profile, state=profile.get("state", {
                        key: value for key, value in profile.items() if key not in metadata}))
                    db.upsert_clue(name, clue, chapter=chapter, commit=False)
                else:
                    db.upsert_foreshadow(name, profile, commit=False)
            for filename, document in documents.items():
                _atomic_write(root / "bible" / filename, json.dumps(document, ensure_ascii=False, indent=2))
            db.conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('bible_signature',?)",
                            (db._bible_signature(),))
            from engine.agents.story_keeper import StoryKeeperAgent
            story = StoryKeeperAgent()
            state = story.load_state(root / "bible")
            overlay_story(root, chapter, state)
            story._sync_promises(state, root / "bible")
            story.save_state(root / "bible", state)
    finally:
        db.close()
