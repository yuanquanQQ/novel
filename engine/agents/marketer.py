# Marketer Agent — 宣传文案生成

import json
import logging
from engine.proxy import config

log = logging.getLogger("marketer")


class MarketerAgent:

    def __init__(self):
        self.model_config = config.writer_model

    def synopsis(self, bible: dict, chapter_summaries: str) -> str:
        from engine.prompts_loader import get_prompt
        prompts, _ = get_prompt("marketer")
        system = prompts["synopsis"]
        chars = bible.get("characters", {}).get("characters", {})
        main = json.dumps(
            {k: {"role": v.get("role", ""), "personality": v.get("personality", "")}
             for k, v in list(chars.items())[:5]},
            ensure_ascii=False, indent=2
        )
        prompt = system.format(
            novel_title=config.story_title,
            world_setting=bible.get("master_bible", "")[:1500],
            main_characters=main,
            chapter_summaries=chapter_summaries[:2000],
        )
        from engine.llm_client import chat
        return chat(self.model_config, user_prompt=prompt)

    def teaser(self, chapter_num: int, chapter_title: str,
               summary: str) -> str:
        from engine.prompts_loader import get_prompt
        prompts, _ = get_prompt("marketer")
        prompt = prompts["teaser"].format(
            novel_title=config.story_title,
            chapter_num=chapter_num,
            chapter_title=chapter_title,
            chapter_summary=summary[:500],
        )
        from engine.llm_client import chat
        return chat(self.model_config, user_prompt=prompt)

    def tags(self, bible: dict, chapter_summaries: str) -> list:
        from engine.prompts_loader import get_prompt
        prompts, _ = get_prompt("marketer")
        prompt = prompts["tags"].format(
            novel_title=config.story_title,
            world_setting=bible.get("master_bible", "")[:1500],
            main_characters=json.dumps(
                list(bible.get("characters", {}).get("characters", {}).keys())[:6],
                ensure_ascii=False
            ),
            chapter_summaries=chapter_summaries[:2000],
        )
        from engine.llm_client import chat_json
        result = chat_json(self.model_config, user_prompt=prompt)
        return result.get("tags", [])

    def author_note(self, progress: str) -> str:
        from engine.prompts_loader import get_prompt
        prompts, _ = get_prompt("marketer")
        prompt = prompts["author_note"].format(
            novel_title=config.story_title,
            inspiration="创作灵感源于对镜像与自我的思考",
            progress=progress,
        )
        from engine.llm_client import chat
        return chat(self.model_config, user_prompt=prompt)

    def cover_art(self, bible: dict) -> str:
        from engine.prompts_loader import get_prompt
        prompts, _ = get_prompt("marketer")
        motifs = bible.get("motif_bank", {}).get("motifs", [])
        imagery = ", ".join(m.get("name", "") for m in motifs[:5])
        prompt = prompts["cover_art"].format(
            novel_title=config.story_title,
            world_setting=bible.get("master_bible", "")[:1000],
            core_imagery=imagery,
            style_ref="Greg Rutkowski, Simon Stalenhag, moody lighting, cinematic composition",
        )
        from engine.llm_client import chat
        return chat(self.model_config, user_prompt=prompt)

    def character_portrait(self, name: str, profile: dict) -> str:
        from engine.prompts_loader import get_prompt
        prompts, _ = get_prompt("marketer")
        prompt = prompts["character_portrait"].format(
            character_profile=json.dumps(profile, ensure_ascii=False, indent=2),
            world_setting="镜影迷城：现代都市与镜像平行世界交织",
        )
        from engine.llm_client import chat
        return chat(self.model_config, user_prompt=prompt)

    def scene_illustration(self, chapter_num: int) -> str:
        from engine.prompts_loader import get_prompt
        prompts, _ = get_prompt("marketer")
        cf = config.generated_dir / f"chapter_{chapter_num:02d}.md"
        scene = cf.read_text(encoding="utf-8")[:800] if cf.exists() else "未生成"
        prompt = prompts["scene_illustration"].format(
            world_setting="镜影迷城：现代都市与镜像平行世界",
            scene_description=scene,
        )
        from engine.llm_client import chat
        return chat(self.model_config, user_prompt=prompt)
