# Foreshadowing Steward — 伏笔管家

import json
import logging
from engine.proxy import config

log = logging.getLogger("steward")


class ForeshadowingSteward:

    def __init__(self):
        self.model_config = config.foreshadowing_steward_model

    def audit(self, plan_json: dict, chapter_num: int,
              bible: dict) -> dict:
        prompt = self._build_prompt(plan_json, chapter_num, bible)
        result = self._call_llm(prompt)
        if result.get("overdue"):
            log.warning(f"过期伏笔: {result['overdue']}")
        if result.get("forgotten_risk"):
            log.warning(f"遗忘风险: {result['forgotten_risk']}")
        return result

    def _build_prompt(self, plan_json: dict, chapter_num: int,
                      bible: dict) -> str:
        from engine.prompts_loader import get_prompt
        system, _ = get_prompt("foreshadowing_steward")

        clues_data = bible.get("clues", {})
        all_fs = clues_data.get("active_foreshadowing", {})
        all_fs_json = json.dumps(all_fs, ensure_ascii=False, indent=2)
        ops = json.dumps(plan_json.get("clue_operations", []),
                         ensure_ascii=False, indent=2)
        plan_str = json.dumps(plan_json, ensure_ascii=False, indent=2)

        summaries = self._read_recent_summaries()

        return system.format(
            all_foreshadowing=all_fs_json,
            plan_json=plan_str,
            clue_operations=ops,
            recent_summaries=summaries,
            chapter_num=chapter_num,
        )

    def _read_recent_summaries(self) -> str:
        gen_dir = config.generated_dir
        if not gen_dir.exists():
            return "无"
        lines = []
        for fp in sorted(gen_dir.glob("chapter_*.md"))[-5:]:
            text = fp.read_text(encoding="utf-8")
            lines.append(text[:100] + "...")
        return "\n".join(lines) if lines else "无"

    def _call_llm(self, prompt: str) -> dict:
        from engine.llm_client import chat_json
        return chat_json(self.model_config, user_prompt=prompt)
