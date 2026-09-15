# Dialogue Auditor — 对话声纹审计师

import json
import logging
from engine.proxy import config

log = logging.getLogger("auditor")


class DialogueAuditor:

    def __init__(self):
        self.model_config = config.immediate_reviewer_model

    def audit(self, draft: str, context_pack: dict,
              scene_type: str = "high_conflict") -> dict:
        prompt = self._build_prompt(draft, context_pack, scene_type)
        result = self._call_llm(prompt)
        violations = result.get("violations", [])
        if not isinstance(violations, list):
            violations = []
        violations = [violation for violation in violations if isinstance(violation, dict)]
        suggestions = self._format_suggestions(violations)
        return {
            "passed": result.get("passed", False) is True,
            "violations": violations,
            "suggestions": suggestions,
        }

    def _build_prompt(self, draft: str, context_pack: dict,
                      scene_type: str) -> str:
        from engine.prompts_loader import get_prompt
        system, _ = get_prompt("dialogue_auditor")
        chars = context_pack.get("relevant_characters", {})
        voice_print = json.dumps(chars, ensure_ascii=False, indent=2)
        ratio_rule = (
            "breathable 场景允许没有对话或仅有少量对话，不按30-45%判失败；"
            "若存在对话，仍需检查声纹和格式。"
            if scene_type == "breathable" else
            "普通场景直接引语目标占比30-45%。"
        )
        return system.format(
            voice_print=voice_print, draft=draft,
        ) + f"\n\n【场景类型】{scene_type}\n【占比规则】{ratio_rule}"

    def _format_suggestions(self, violations: list) -> str:
        if not violations:
            return ""
        lines = []
        for v in violations:
            lines.append(
                f"[{v.get('character','?')}]{v.get('issue','')}: "
                f"{v.get('fix','')}"
            )
        return "; ".join(lines)

    def _call_llm(self, prompt: str) -> dict:
        from engine.llm_client import chat_json
        return chat_json(self.model_config, user_prompt=prompt)
