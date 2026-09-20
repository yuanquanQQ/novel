# Dialogue Auditor — 对话声纹审计师

import json
import logging
import re
from engine.proxy import config
from engine.quality import validate_verdict

log = logging.getLogger("auditor")


class DialogueAuditor:

    def __init__(self):
        self.model_config = config.immediate_reviewer_model

    def audit(self, draft: str, context_pack: dict,
              scene_type: str = "high_conflict") -> dict:
        prompt = self._build_prompt(draft, context_pack, scene_type)
        try:
            result = validate_verdict(self._call_llm(prompt), "violations")
        except Exception as exc:
            log.warning("对话审阅不可用: %s", exc)
            result = validate_verdict(None, "violations")
        violations = result["violations"]
        original_violations = violations
        # 只过滤要求改回旧式引号的误报，保留缺失引号等真实格式问题。
        if not re.search(r'["「」『』【】]', draft):
            violations = [
                v for v in violations
                if not (str(v.get("issue", "")).find("格式") >= 0
                        and any(style in str(v.get("fix", "")) for style in ("直角", "「", "【")))
            ]
        filtered_only = bool(original_violations) and not violations and not result.get("unavailable")
        suggestions = "" if filtered_only else self._format_suggestions(violations) or result.get("suggestions", "")
        return {
            "passed": (result["passed"] or filtered_only) and not violations,
            "violations": violations,
            "suggestions": suggestions,
            "unavailable": result.get("unavailable", False),
        }

    def _build_prompt(self, draft: str, context_pack: dict,
                      scene_type: str) -> str:
        from engine.prompts_loader import get_prompt
        system, _ = get_prompt("dialogue_auditor")
        chars = context_pack.get("relevant_characters", {})
        voice_print = json.dumps(chars, ensure_ascii=False, indent=2)
        ratio_rule = (
            "breathable 场景允许没有对话或仅有少量对话；"
            "若存在对话，仍需检查声纹和格式。"
            if scene_type == "breathable" else
            "对话比例服从场景任务，不因比例、完整句、自然转述或没有口癖判失败。"
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
