# Writer Agent — 正文撰写与章节合并

import json
import logging
from engine.proxy import config

log = logging.getLogger("writer")


class WriterAgent:

    def __init__(self):
        self.model_config = config.writer_model

    def run(self, scene: dict, keeper_cache: dict,
            context_pack: dict, chapter_num: int,
            feedback: str = "") -> str:
        scene_id = scene.get("scene_id", "?")
        log.info(f"Writer — 撰写场景 {scene_id}")

        prompt = self._build_prompt(
            scene, keeper_cache, context_pack, chapter_num, feedback
        )
        return self._call_llm(prompt, scene_id)

    def _build_prompt(self, scene: dict, keeper_cache: dict,
                      context_pack: dict, chapter_num: int,
                      feedback: str) -> str:
        from engine.prompts_loader import get_prompt
        system, _ = get_prompt("writer")

        scene_id = scene.get("scene_id", 1)
        scene_type = scene.get("type", "high_conflict")

        running_ctx = keeper_cache.get("running_context", "(无上下文)")
        scene_plan_json = json.dumps(scene, ensure_ascii=False, indent=2)

        chars = context_pack.get("relevant_characters", {})
        voice_print = json.dumps(chars, ensure_ascii=False, indent=2)

        research_ctx = self._format_research_context(context_pack)
        hooks = self._format_chapter_hooks(
            context_pack.get("_plan", {})
        )

        special = self._build_special_condition(scene, scene_type, feedback)
        feedback_block = self._build_feedback_block(feedback)

        base_prompt = system.format(
            novel_title=config.story_title,
            chapter_num=chapter_num,
            scene_id=scene_id,
            keeper_cache=running_ctx,
            scene_plan=scene_plan_json,
            characters_voice_print=voice_print,
            research_context=research_ctx,
            chapter_hooks=hooks,
            special_condition=special,
            style_watch=context_pack.get("style_watch", "（无）"),
        )
        # feedback_block 追加在末尾——模型对 prompt 末尾注意力最高
        return base_prompt + feedback_block

    def _format_research_context(self, context_pack: dict) -> str:
        parts = []
        notes = context_pack.get("research_notes", "")
        if notes:
            parts.append(notes)
        mem = context_pack.get("memory_notes", "")
        if mem:
            parts.append("## 运行时知识库（与正文冲突时以此为准）\n" + mem)
        clues = context_pack.get("relevant_clues", {})
        if clues:
            parts.append("## 活跃线索\n" + json.dumps(
                clues, ensure_ascii=False, indent=2
            ))
        motifs = context_pack.get("suggested_motifs", [])
        if motifs:
            motif_names = [m.get("name", "") for m in motifs[:3]]
            parts.append("推荐母题: " + ", ".join(motif_names))
        return "\n".join(parts) if parts else "(无额外研究资料)"

    def _format_chapter_hooks(self, plan: dict) -> str:
        hooks = plan.get("chapter_hooks", {})
        if not hooks:
            return ""
        return (f"明钩: {hooks.get('light_hook', '')}\n"
                f"暗钩: {hooks.get('dark_hook', '')}")

    def _build_special_condition(self, scene: dict, scene_type: str,
                                 feedback: str) -> str:
        parts = []
        if scene_type == "breathable":
            parts.append(
                "本场景为 breathable（低对白缓冲）：允许完全无对话或仅有少量自然对话，"
                "不要求达到普通场景30-45%的对话占比。重点写环境、光影、微动作与内心流动。"
            )
        sanity = scene.get("sanity_score", 0.8)
        if sanity < 0.6:
            parts.append(
                "当前 POV 人物 sanity_score={:.1f}<0.6：感官描写允许"
                "轻微扭曲（时钟倒转、水滴上坠），人物浑然不觉。".format(sanity)
            )
        return "\n".join(parts) if parts else "无特殊条件。"

    def _build_feedback_block(self, feedback: str) -> str:
        """把 reviewer 的反馈转成逐条强制执行清单，独立于 special_condition 追加在 prompt 末尾。"""
        if not feedback:
            return ""

        import re
        raw_items = re.split(r"[；;]", feedback)
        items = [item.strip() for item in raw_items if item.strip()]
        if not items:
            return ""

        lines = [
            "\n\n════════════════════════════════",
            "【强制修改清单——逐条执行，不得跳过】",
            "以下每一条都是上一轮审阅发现的问题，本次必须全部修复：",
        ]
        for i, item in enumerate(items, 1):
            lines.append(f"  {i}. {item}")
        lines.append(
            "\n修完后自查：上面每条都改了吗？"
            "有没有顺手把禁用词（然而/因此/于是/不禁/愈发/深邃/宛若/在这一刻）带回来？"
        )
        lines.append("════════════════════════════════")
        return "\n".join(lines)

    def _call_llm(self, prompt: str, scene_id: int) -> str:
        from engine.llm_client import chat
        return chat(self.model_config, user_prompt=prompt)

    def merge_scenes(self, all_scenes: list, plan_json: dict,
                      chapter_num: int) -> str:
        log.info(f"Writer — 合并第 {chapter_num} 章 ({len(all_scenes)} 个场景)")
        lines = []
        for scene_text in all_scenes:
            lines.append(scene_text.strip())
            lines.append("")
        return "\n\n".join(lines).strip()

    def apply_patches(self, full_chapter: str, plan_json: dict,
                      patch_instructions: list, chapter_num: int) -> str:
        """应用重型审查的 patch_instructions 进行章节修订"""
        if not patch_instructions:
            return full_chapter
        log.info(f"Writer — 应用 {len(patch_instructions)} 条修订指示")

        from engine.prompts_loader import _banned_words_inline
        instructions_text = "\n".join(f"{i+1}. {p}" for i, p in enumerate(patch_instructions))
        prompt = (
            "你是有十年经验的网文作者，现在在番茄连载。请根据以下【修改清单】逐条修订正文，"
            "每一条都必须执行，不得跳过。只改清单涉及的部分，其余保留原文。\n\n"
            "【修改清单】\n"
            + instructions_text +
            "\n\n【铁律——修改时同样适用】\n"
            + _banned_words_inline() +
            "\n修订后不得引入新的机械违规（扫描器会复检）。\n\n"
            f"【原文】\n{full_chapter}\n\n"
            "输出修订后的完整正文，不要任何说明或注释。"
        )
        return self._call_llm(prompt, 0)