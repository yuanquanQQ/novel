"""Select relevant, due and long-unanswered story memory without mutating canon."""
from copy import deepcopy
import json


def select_memory(state, chapter, query=None, fact_limit=160, issue_limit=8):
    query = query or {}
    text = query if isinstance(query, str) else json.dumps(query, ensure_ascii=False)
    entities = query.get("entities", {}) if isinstance(query, dict) else {}
    explicit = {name for values in entities.values() if isinstance(values, list)
                for name in values if isinstance(name, str)} if isinstance(entities, dict) else set()

    def relevance(name, item):
        payload = json.dumps(item, ensure_ascii=False)
        return (100 if name in explicit else 0) + (20 if name and name in text else 0) + sum(
            5 for term in explicit if term and term in payload)

    facts = []
    for name, attrs in state.get("facts", {}).items():
        for attr, item in attrs.items():
            history = [n for n in item.get("chapters", []) if isinstance(n, int)]
            latest = max(history, default=0)
            if latest >= chapter:
                continue
            score = relevance(name, item) + (3 if attr in text else 0)
            facts.append((score, latest, name, attr, item))
    facts.sort(key=lambda row: (-row[0], -row[1], row[2], row[3]))
    selected = deepcopy(state)
    selected["facts"] = {}
    for _, _, name, attr, item in facts[:fact_limit]:
        selected["facts"].setdefault(name, {})[attr] = deepcopy(item)

    def ranked(items, date_key):
        candidates = []
        for name, item in items:
            raised = item.get(date_key) or 0
            if raised >= chapter or item.get("status") in ("resolved", "retired"):
                continue
            due = item.get("payoff_end_chapter") or item.get("intended_payoff_chapter")
            overdue = isinstance(due, int) and due <= chapter
            score = relevance(name, item) + (50 if overdue else 0)
            candidates.append((score, raised, name, item))
        # Equal relevance favours the oldest promise, not the newest distraction.
        candidates.sort(key=lambda row: (-row[0], row[1], row[2]))
        return [(name, deepcopy(item)) for _, _, name, item in candidates[:issue_limit]]

    selected["open_questions"] = [item for _, item in ranked(
        ((q.get("id", ""), q) for q in state.get("open_questions", []) if q.get("status") == "open"),
        "raised_chapter")]
    selected["unresolved_promises"] = dict(ranked(state.get("unresolved_promises", {}).items(), "planted_chapter"))
    selected["character_arcs"] = dict(ranked(state.get("character_arcs", {}).items(), "last_chapter"))
    selected["continuity_warnings"] = sorted(
        [deepcopy(w) for w in state.get("continuity_warnings", []) if w.get("chapter", 0) < chapter],
        key=lambda w: (relevance(w.get("entity", ""), w), w.get("severity") == "major", w.get("chapter", 0)),
        reverse=True)[:issue_limit]
    return selected
