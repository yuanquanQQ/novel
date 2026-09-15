# Planner Agent — 生成章节大纲与节奏规划

import json
import logging
import re

from engine.chapter_files import chapter_files
from engine.proxy import config

log = logging.getLogger("planner")

ENTITY_FIELDS = (
    "characters", "locations", "objects", "factions", "abilities", "clue_ids"
)
FORESHADOW_ACTIONS = {
    "plant", "hint", "escalate", "reveal", "reschedule", "retire",
}


class PlanValidationError(ValueError):
    pass
_SECTION_RE = re.compile(r"^### 第(\d+)-(\d+)章：([^\n]+)$")
_CHAPTER_BULLET_RE = re.compile(
    r"^- \*\*第(\d+)章 ([^*\n]+)\*\*：(.+)。\*功能："
    r"([^*\n；]+(?:；[^*\n]+)*?)；伏笔："
    r"(?:(?:引入|推进|回收) F\d{3}|无)\*$"
)


def parse_outline_context(outline: str, chapter_num: int, radius: int = 2) -> dict:
    entries = []
    current_section = ""
    for line in outline.splitlines():
        section_match = _SECTION_RE.fullmatch(line)
        if section_match:
            current_section = line
            continue
        chapter_match = _CHAPTER_BULLET_RE.fullmatch(line)
        if chapter_match:
            entries.append({
                "chapter": int(chapter_match.group(1)),
                "section": current_section,
                "bullet": line,
            })

    entries.sort(key=lambda item: item["chapter"])
    position = next(
        (index for index, item in enumerate(entries)
         if item["chapter"] == chapter_num),
        None,
    )
    if position is None:
        return {"chapter": chapter_num, "section": "", "current": "", "neighbors": []}

    current = entries[position]
    start = max(0, position - radius)
    end = min(len(entries), position + radius + 1)
    return {
        "chapter": chapter_num,
        "section": current["section"],
        "current": current["bullet"],
        "neighbors": entries[start:end],
    }


def format_outline_context(context: dict) -> str:
    if not context.get("current"):
        return "(outline.md 中未找到符合严格 bullet 格式的本章规划)"
    lines = [f"所属小节：{context['section'] or '(未标注)'}", "相邻章节规划："]
    for item in context["neighbors"]:
        marker = "【当前章】" if item["chapter"] == context["chapter"] else ""
        lines.append(f"{marker}{item['bullet']}")
    return "\n".join(lines)


class PlannerAgent:
    """负责生成本章详细大纲，含情绪曲线、呼吸节律、镜像母题、三明治钩子"""

    def __init__(self):
        self.model_config = config.planner_model

    def run(self, chapter_num: int, instruction: str,
            bible: dict, lessons: list, locked_title: str = "") -> dict:
        log.info(f"Planner — 规划第 {chapter_num} 章")

        prompt = self._build_prompt(chapter_num, instruction, bible,
                                    lessons, locked_title)
        plan_json = self._call_llm(prompt)
        plan_json = self._validate_and_normalize(plan_json, chapter_num)
        if locked_title:
            plan_json["chapter_title"] = locked_title
        return plan_json

    def _build_prompt(self, chapter_num: int, instruction: str,
                      bible: dict, lessons: list,
                      locked_title: str = "") -> str:
        from engine.prompts_loader import get_prompt, get_meta
        system, template = get_prompt("planner")

        master_bible = bible.get("master_bible", "")
        characters_json = json.dumps(bible.get("characters", {}),
                                     ensure_ascii=False, indent=2)
        clues_json = json.dumps(bible.get("clues", {}),
                                ensure_ascii=False, indent=2)
        motif_bank_json = json.dumps(bible.get("motif_bank", {}),
                                     ensure_ascii=False, indent=2)
        lessons_text = json.dumps(lessons, ensure_ascii=False, indent=2)
        recent_summary = self._read_outline_summary(chapter_num)
        outline_context = self._read_outline_context(chapter_num)

        volume = self._get_volume_info(chapter_num)
        title_hint = f"\n\n【锁定标题】本章标题已确定为「{locked_title}」，所有场景设计必须围绕此标题展开。" if locked_title else ""
        entities_contract = (
            "\n\n【实体输出契约】输出 JSON 必须包含 entities 对象，且 characters、locations、"
            "objects、factions、abilities、clue_ids 均为字符串数组，只列本章实际相关实体。"
        )

        system_filled = system.format(chapter_num=chapter_num, novel_title=get_meta().get("novel", ""))
        user = template.format(
            master_bible=master_bible,
            characters_json=characters_json,
            clues_json=clues_json,
            motif_bank_json=motif_bank_json,
            lessons_learned=lessons_text,
            outline_summary=recent_summary,
            chapter_num=chapter_num,
            instruction=instruction,
            volume_name=volume.get("name", ""),
            volume_emotion=volume.get("core_emotion", ""),
            volume_focus=volume.get("focus", ""),
        )
        user += f"\n\n## outline.md 当前章上下文（必须遵循）\n{outline_context}"
        return system_filled + entities_contract + "\n\n" + user + title_hint

    def _get_volume_info(self, chapter_num: int) -> dict:
        for vol in config.volume_config.values():
            lo, hi = vol["chapters"]
            if lo <= chapter_num <= hi:
                return vol
        return {}

    def _read_outline_context(self, chapter_num: int) -> str:
        outline_file = config.bible_dir / "outline.md"
        if not outline_file.exists():
            return "(未找到 bible/outline.md)"
        outline = outline_file.read_text(encoding="utf-8")
        return format_outline_context(parse_outline_context(outline, chapter_num))

    def _read_outline_summary(self, chapter_num: int) -> str:
        from engine.db import NovelDB
        try:
            db = NovelDB(config.bible_dir.parent)
            try:
                rows = db.recent_summaries(chapter_num, 10)
            finally:
                db.close()
            if rows:
                return "\n".join(
                    f"- 第{row['chapter']}章: {row['summary']}" for row in rows
                )
        except Exception as e:
            log.warning(f"章节摘要数据库读取失败，回退正文首行: {e}")
        lines = []
        for fp in chapter_files(
            config.generated_dir, before_chapter=chapter_num, limit=10
        ):
            content = fp.read_text(encoding="utf-8")
            first_line = content.strip().split("\n")[0] if content else fp.stem
            lines.append(f"- {first_line}")
        return "\n".join(lines) if lines else "(尚无已写章节)"

    def _validate_and_normalize(self, plan: dict, chapter_num: int) -> dict:
        if not isinstance(plan, dict):
            plan = {}
        plan.setdefault("chapter_title", f"第 {chapter_num} 章")
        plan.setdefault("emotional_arc", [])
        plan.setdefault("clue_operations", [])
        plan.setdefault("chapter_hooks", {"light_hook": "", "dark_hook": ""})
        raw_ops = plan["clue_operations"]
        if not isinstance(raw_ops, list):
            raise PlanValidationError("clue_operations 必须是数组")
        normalized_ops = []
        seen = set()
        for index, raw in enumerate(raw_ops, 1):
            if not isinstance(raw, dict):
                raise PlanValidationError(f"第{index}个伏笔操作必须是对象")
            op = dict(raw)
            action = str(op.get("action", "")).strip().lower()
            fid = str(op.get("clue_id", op.get("id", ""))).strip()
            if action not in FORESHADOW_ACTIONS:
                raise PlanValidationError(f"伏笔 {fid or index} 的 action 无效: {action}")
            if not re.fullmatch(r"F[0-9A-Za-z_-]+", fid):
                raise PlanValidationError(f"第{index}个伏笔操作缺少有效 clue_id")
            key = (action, fid)
            if key in seen:
                raise PlanValidationError(f"重复伏笔操作: {action} {fid}")
            seen.add(key)
            op["action"], op["clue_id"] = action, fid
            if action == "plant":
                if not str(op.get("name", "")).strip() or not str(op.get("description", "")).strip():
                    raise PlanValidationError(f"plant {fid} 必须包含 name 和 description")
                op.setdefault("introduced_chapter", chapter_num)
            if action == "reschedule" and not any(
                op.get(field) is not None for field in (
                    "intended_payoff_chapter", "payoff_start_chapter", "payoff_end_chapter"
                )
            ):
                raise PlanValidationError(f"reschedule {fid} 必须提供回收章节或窗口")
            normalized_ops.append(op)
        plan["clue_operations"] = normalized_ops

        raw_entities = plan.get("entities")
        raw_entities = raw_entities if isinstance(raw_entities, dict) else {}
        plan["entities"] = {
            field: list(dict.fromkeys(
                value for value in raw_entities.get(field, [])
                if isinstance(value, str) and value.strip()
            )) if isinstance(raw_entities.get(field, []), list) else []
            for field in ENTITY_FIELDS
        }

        scenes = plan.get("scene_outline", [])
        if not scenes:
            log.warning("大纲无场景，自动生成兜底场景")
            scenes = [{
                "scene_id": 1,
                "type": "high_conflict",
                "target_emotion": 0.8,
                "description": "本章核心事件",
                "physical_mirror": "",
                "narrative_mirror": "",
                "sanity_score": 0.8,
            }]
            plan["scene_outline"] = scenes

        for i, scene in enumerate(scenes):
            scene.setdefault("scene_id", i + 1)
            scene.setdefault("type", "high_conflict")
            scene.setdefault("target_emotion", 0.7)
            scene.setdefault("description", "")
            scene.setdefault("physical_mirror", "")
            scene.setdefault("narrative_mirror", "")
            scene.setdefault("sanity_score", 0.8)

        return plan

    def _call_llm(self, prompt: str) -> dict:
        from engine.llm_client import chat_json
        return chat_json(self.model_config, user_prompt=prompt)
