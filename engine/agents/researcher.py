# Researcher Agent — 章节相关知识与资料检索

import json
import logging
from engine.proxy import config

log = logging.getLogger("researcher")


class ResearcherAgent:
    """检索 Bible 知识库，为当前章节提供上下文资料包"""

    def __init__(self):
        self.model_config = config.researcher_model

    def run(self, plan_json: dict, chapter_num: int,
            bible: dict) -> dict:
        log.info(f"Researcher — 为第 {chapter_num} 章检索资料")

        characters = bible.get("characters", {}).get("characters", {})
        clues_data = bible.get("clues", {})
        clues = clues_data.get("clues", {})
        foreshadowing = clues_data.get("active_foreshadowing", {})
        motifs_raw = bible.get("motif_bank", {}).get("motifs", [])
        master_bible = bible.get("master_bible", "")

        available_motifs = self._filter_motifs(motifs_raw, chapter_num)
        relevant_foreshadowing = self._extract_pending_foreshadowing(
            foreshadowing
        )
        research_notes = self._build_research_notes(
            plan_json, clues, characters, chapter_num
        )

        return {
            "chapter": chapter_num,
            "relevant_characters": characters,
            "relevant_clues": clues,
            "relevant_locations": self._extract_locations(characters),
            "relevant_foreshadowing": relevant_foreshadowing,
            "suggested_motifs": available_motifs,
            "recent_chapters_summary": self._read_recent_summaries(),
            "research_notes": research_notes,
            **self._db_context(plan_json, chapter_num),
        }

    def _db_context(self, plan_json: dict, chapter_num: int) -> dict:
        """从运行时知识库检索：跨章事实、人物状态时间线、伏笔健康度、风格惯性。"""
        import json as _json
        from engine.db import NovelDB
        from engine.settings import get_novel_dir
        try:
            db = NovelDB(get_novel_dir())
        except Exception as e:
            log.warning(f"DB 不可用: {e}")
            return {}
        out = {}
        try:
            plan_text = _json.dumps(plan_json, ensure_ascii=False)
            names = [r["name"] for r in
                     db.conn.execute("SELECT name FROM characters").fetchall()]
            hit_names = [n for n in names if n and n in plan_text]
            facts = db.search_facts(hit_names or names[:5], chapter_num, 20)
            states = db.recent_states(hit_names[:6], chapter_num, 2)
            fore = db.open_foreshadowing(chapter_num)
            hits = db.top_style_hits(chapter_num, 5)

            mem = []
            if states:
                mem.append("### 人物近况（数据库时间线）")
                mem += [f"- [第{s['chapter']}章] {s['character']}: "
                        f"{s['state_json'][:150]}" for s in states]
            if facts:
                mem.append("### 相关跨章事实（不得与之矛盾）")
                mem += [f"- [第{r['chapter']}章|{r['kind']}] {r['subject']}: {r['content']}"
                        for r in facts]
            if mem:
                out["memory_notes"] = "\n".join(mem)

            watch = []
            if fore["overdue_to_payoff"]:
                watch.append("【伏笔到期未收!】" + "；".join(
                    f"{f['id']}{f['name']}(计划第{f['payoff_ch']}章收)"
                    for f in fore["overdue_to_payoff"][:3]))
            if fore["stale"]:
                watch.append("【已遗忘】" + "；".join(
                    f"{f['name']}暗了{f['days_dark']}章" for f in fore["stale"][:3]))
            if hits:
                watch.append("【本章高频踩雷，格外避开】" + "、".join(
                    f"{h['pattern']}x{h['total']}" for h in hits))
            if watch:
                out["style_watch"] = "\n".join(watch)
        except Exception as e:
            log.warning(f"DB 检索失败(降级为JSON模式): {e}")
        finally:
            db.close()
        return out

    def _filter_motifs(self, motifs_raw: list, chapter_num: int) -> list:
        available = []
        for m in motifs_raw:
            used = m.get("used_in_chapters", [])
            if chapter_num not in used:
                available.append({
                    "id": m.get("id"), "name": m.get("name"),
                    "description": m.get("description"),
                    "usage_ideas": m.get("usage_ideas", []),
                })
        return available

    def _extract_pending_foreshadowing(self, foreshadowing: dict) -> dict:
        return {
            k: v for k, v in foreshadowing.items()
            if v.get("status") == "pending"
        }

    def _extract_locations(self, characters: dict) -> dict:
        locations = {}
        for name, profile in characters.items():
            loc = profile.get("current_location")
            if loc:
                locations.setdefault(loc, []).append(name)
        return locations

    def _read_recent_summaries(self) -> str:
        gen_dir = config.generated_dir
        if not gen_dir.exists():
            return "(无已写章节)"
        chapters = sorted(gen_dir.glob("chapter_*.md"))
        if not chapters:
            return "(无已写章节)"
        lines = []
        for fp in chapters[-3:]:
            content = fp.read_text(encoding="utf-8")
            first_line = (content.strip().split("\n")[0]
                          if content else fp.stem)
            lines.append(first_line)
        return "\n".join(lines)

    def _build_research_notes(self, plan_json: dict, clues: dict,
                              characters: dict, chapter_num: int) -> str:
        from engine.llm_client import chat
        from engine.prompts_loader import get_prompt
        system, chapter_template = get_prompt("researcher")
        prompt = chapter_template.format(
            plan_json=json.dumps(plan_json, ensure_ascii=False, indent=2),
            search_results=json.dumps(
                {"clues": clues, "characters": list(characters.keys())},
                ensure_ascii=False, indent=2,
            ),
            chapter_num=chapter_num,
        )
        return chat(self.model_config, system_prompt=system,
                     user_prompt=prompt)
