# 共享 LLM 客户端 — 所有 Agent 的统一 API 调用入口

import json
import time
import logging
from openai import OpenAI
from engine.proxy import config

log = logging.getLogger("llm_client")

_client = None
_client_identity = None


def get_client() -> OpenAI:
    global _client, _client_identity
    api_key = getattr(config, 'api_key', None) or getattr(config, 'deepseek_api_key', '')
    base_url = getattr(config, 'base_url', None) or getattr(config, 'deepseek_base_url', '')
    identity = (api_key, base_url)
    if _client is None or _client_identity != identity:
        _client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0)
        _client_identity = identity
    return _client


def chat(model_cfg, system_prompt: str = "", user_prompt: str = "",
         response_json: bool = False, max_retries: int = 5) -> str:
    """
    统一的 LLM 调用。

    参数:
        model_cfg:     ModelConfig 对象
        system_prompt: 系统提示词 (可选)
        user_prompt:   用户提示词 (可选)
        response_json: 是否要求 JSON 输出
        max_retries:   最大重试次数

    Returns:
        LLM 原始文本响应
    """
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if user_prompt:
        messages.append({"role": "user", "content": user_prompt})
    if not messages:
        messages.append({"role": "user", "content": system_prompt})

    client = get_client()
    kwargs = {
        "model": model_cfg.model_name,
        "messages": messages,
        "temperature": model_cfg.temperature,
        "max_tokens": model_cfg.max_tokens,
        "top_p": model_cfg.top_p,
    }
    if response_json:
        _url = getattr(config, 'base_url', None) or getattr(config, 'deepseek_base_url', '')
        if "localhost" in _url or "127.0.0.1" in _url:
            if messages:
                messages[-1]["content"] += "\n\n请只输出JSON，不要任何其他文字。"
        else:
            kwargs["response_format"] = {"type": "json_object"}

    last_error = None
    for attempt in range(max_retries):
        from engine.usage import reserve_call, record_call
        reserve_call()
        started, response = time.monotonic(), None
        try:
            log.info(f"LLM 调用: {model_cfg.model_name} "
                     f"(attempt {attempt + 1}/{max_retries})")
            response = client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
            if not isinstance(content, str) or not content.strip():
                raise ValueError("模型返回空正文")
            if getattr(response.choices[0], "finish_reason", None) == "length":
                raise ValueError("模型输出被长度上限截断")
            record_call(model_cfg.model_name, started, response=response)
            log.info(f"LLM 响应: {len(content)} 字符")
            return content
        except Exception as e:
            record_call(model_cfg.model_name, started, response=response, error=e)
            last_error = e
            err_str = str(e)
            # 429/rate limit: 等久一点
            if "429" in err_str or "rate" in err_str.lower() or "exhausted" in err_str.lower():
                delay = min(5 * (2 ** attempt), 60)
                log.warning(f"速率限制，{delay}秒后重试...")
            else:
                delay = 2 ** attempt
                log.warning(f"LLM 调用失败 (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(delay)

    raise last_error


def chat_json(model_cfg, system_prompt: str = "",
              user_prompt: str = "", max_retries: int = 3) -> dict:
    """
    调用 LLM 并解析 JSON 响应。
    自动处理 markdown 代码块包裹。
    """
    raw = chat(model_cfg, system_prompt, user_prompt,
               response_json=True, max_retries=max_retries)
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = lines[1:] if lines[0].startswith("```") else lines
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines)
    try:
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError(f"LLM JSON 响应必须是对象，实际为 {type(result).__name__}")
        return result
    except (json.JSONDecodeError, ValueError):
        log.warning(f"JSON 解析失败 ({len(raw)} 字符)，尝试修复...")
        try:
            import re
            match = re.search(r'\{[\s\S]*\}', raw)
            if match:
                result = json.loads(match.group(0))
                if not isinstance(result, dict):
                    raise ValueError(f"LLM JSON 响应必须是对象，实际为 {type(result).__name__}")
                return result
        except Exception:
            pass
        if max_retries > 1:
            log.info(f"JSON 解析失败，重试 ({max_retries - 1} 次剩余)")
            return chat_json(model_cfg, system_prompt, user_prompt, max_retries - 1)
        raise ValueError("LLM JSON 响应无效，JSON 解析和修复均失败")
