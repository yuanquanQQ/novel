# Planner Agent — 生成章节大纲与节奏规划

import json
import logging
from engine.proxy import config

log = logging.getLogger("planner")


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
        outline_summary = self._read_outline_summary()

        volume = self._get_volume_info(chapter_num)
        title_hint = f"\n\n【锁定标题】本章标题已确定为「{locked_title}」，所有场景设计必须围绕此标题展开。" if locked_title else ""

        system_filled = system.format(chapter_num=chapter_num, novel_title=get_meta().get("novel", ""))
        user = template.format(
            master_bible=master_bible,
            characters_json=characters_json,
            clues_json=clues_json,
            motif_bank_json=motif_bank_json,
            lessons_learned=lessons_text,
            outline_summary=outline_summary,
            chapter_num=chapter_num,
            instruction=instruction,
            volume_name=volume.get("name", ""),
            volume_emotion=volume.get("core_emotion", ""),
            volume_focus=volume.get("focus", ""),
        ) + title_hint
        return system_filled + "\n\n" + user

    def _get_volume_info(self, chapter_num: int) -> dict:
        for vol in config.volume_config.values():
            lo, hi = vol["chapters"]
            if lo <= chapter_num <= hi:
                return vol
        return {}

    def _read_outline_summary(self) -> str:
        gen_dir = config.generated_dir
        if not gen_dir.exists():
            return "(尚无已写章节)"
        chapters = sorted(gen_dir.glob("chapter_*.md"))
        if not chapters:
            return "(尚无已写章节)"
        lines = []
        for fp in chapters[-10:]:
            content = fp.read_text(encoding="utf-8")
            first_line = (content.strip().split("\n")[0]
                          if content else fp.stem)
            lines.append(f"- {first_line}")
        return "\n".join(lines)

    def _validate_and_normalize(self, plan: dict, chapter_num: int) -> dict:
        plan.setdefault("chapter_title", f"第 {chapter_num} 章")
        plan.setdefault("emotional_arc", [])
        plan.setdefault("clue_operations", [])
        plan.setdefault("chapter_hooks", {"light_hook": "", "dark_hook": ""})

        scenes = plan.get("scene_outline", [])
        if not scenes:
            log.warning(f"大纲无场景，自动生成兜底场景")
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
