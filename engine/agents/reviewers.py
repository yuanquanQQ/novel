# Reviewers — 即时审阅 + 重型审阅

import json
import logging
from engine.proxy import config

log = logging.getLogger("reviewers")


class ReviewerAgent:

    def __init__(self):
        self.immediate_config = config.immediate_reviewer_model
        self.heavy_config = config.heavy_reviewer_model

    def immediate_check(self, draft: str, scene: dict,
                        keeper_cache: dict, context_pack: dict = None) -> dict:
        scene_id = scene.get("scene_id", "?")
        log.info(f"ImmediateReview — 场景 {scene_id}")

        prompt = self._build_immediate_prompt(draft, keeper_cache, scene,
                                              context_pack)
        result = self._call_immediate_llm(prompt)

        errors = result.get("errors", [])
        if not isinstance(errors, list):
            errors = []
        errors = [error for error in errors if isinstance(error, dict)]
        suggestions = self._format_suggestions(errors)
        return {
            "passed": result.get("passed", False) is True,
            "errors": errors,
            "suggestions": suggestions,
        }

    def _build_immediate_prompt(self, draft: str, keeper_cache: dict,
                                scene: dict,
                                context_pack: dict = None) -> str:
        from engine.prompts_loader import get_prompt
        system, _ = get_prompt("reviewer_immediate")

        running_ctx = keeper_cache.get("running_context", "(无上下文)")
        scene_type = scene.get("type", "")
        prompt = system.format(
            keeper_cache=running_ctx,
            draft=draft,
        )
        if scene_type:
            prompt += f"\n\n【场景类型】{scene_type}"
        if context_pack:
            chars = context_pack.get("relevant_characters", {})
            if chars:
                prompt += f"\n\n【声纹档案】\n{json.dumps(chars, ensure_ascii=False, indent=2)}"
        return prompt

    def _format_suggestions(self, errors: list) -> str:
        if not errors:
            return ""
        lines = []
        for e in errors:
            lines.append(
                f"[{e.get('type', '?')}] "
                f"{e.get('paragraph', '')[:80]} → "
                f"{e.get('suggestion', '')}"
            )
        return "\n".join(lines)

    def _call_immediate_llm(self, prompt: str) -> dict:
        from engine.llm_client import chat_json
        return chat_json(self.immediate_config, user_prompt=prompt)

    def heavy_check(self, full_chapter: str, plan_json: dict,
                    chapter_num: int) -> dict:
        log.info(f"HeavyReview — 第 {chapter_num} 章")

        prompt = self._build_heavy_prompt(full_chapter, plan_json)
        result = self._call_heavy_llm(prompt)
        log.info(f"HeavyReview 评分: {result.get('score', '?')}")
        return result

    def _build_heavy_prompt(self, full_chapter: str,
                            plan_json: dict) -> str:
        from engine.prompts_loader import get_prompt
        system, _ = get_prompt("reviewer_heavy")
        plan_str = json.dumps(plan_json, ensure_ascii=False, indent=2)
        return system.format(
            plan_json=plan_str,
            full_chapter=full_chapter,
        )

    def _call_heavy_llm(self, prompt: str) -> dict:
        from engine.llm_client import chat_json
        return chat_json(self.heavy_config, user_prompt=prompt)
