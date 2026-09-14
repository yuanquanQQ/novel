# Reader Proxy — 读者代理人

import json
import logging
from engine.proxy import config

log = logging.getLogger("reader")


class ReaderProxy:

    def __init__(self):
        self.model_config = config.reader_proxy_model

    def read(self, full_chapter: str) -> dict:
        prompt = self._build_prompt(full_chapter)
        result = self._call_llm(prompt)
        log.info(f"读者评分: {result.get('overall_score', '?')}")
        if result.get("confusion_points"):
            log.warning(f"困惑点: {len(result['confusion_points'])} 处")
        return result

    def _build_prompt(self, full_chapter: str) -> str:
        from engine.prompts_loader import get_prompt
        system, _ = get_prompt("reader_proxy")
        return system.format(full_chapter=full_chapter)

    def _call_llm(self, prompt: str) -> dict:
        from engine.llm_client import chat_json
        return chat_json(self.model_config, user_prompt=prompt)
