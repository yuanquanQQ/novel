"""Generate standalone novel theme suggestions with an OpenAI-compatible API."""

import hashlib
import json
import os
import re
from typing import Mapping

from openai import OpenAI

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"
_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")


class ThemeConfigurationError(ValueError):
    """The theme generation API is not configured correctly."""


class ThemeGenerationError(RuntimeError):
    """The model call or its response could not produce valid themes."""


def _environment_value(environ: Mapping[str, str], primary: str, fallback: str, default: str = "") -> str:
    return (environ.get(primary) or environ.get(fallback) or default).strip()


def _configuration(environ: Mapping[str, str]) -> tuple[str, str, str]:
    api_key = _environment_value(environ, "API_KEY", "DEEPSEEK_API_KEY")
    if not api_key or api_key.lower() == "your-api-key-here":
        fallback_key = (environ.get("DEEPSEEK_API_KEY") or "").strip()
        api_key = fallback_key if fallback_key.lower() != "your-api-key-here" else ""
    if not api_key:
        raise ThemeConfigurationError(
            "未配置主题构思 API 密钥，请设置 API_KEY 或 DEEPSEEK_API_KEY"
        )
    base_url = _environment_value(
        environ, "API_BASE_URL", "DEEPSEEK_BASE_URL", DEFAULT_BASE_URL
    )
    model = (environ.get("THEME_MODEL") or DEFAULT_MODEL).strip()
    return api_key, base_url, model


def _required_text(option: dict, field: str, index: int, max_length: int) -> str:
    value = option.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ThemeGenerationError(f"第 {index} 个方案的 {field} 必须是非空字符串")
    value = value.strip()
    if len(value) > max_length:
        raise ThemeGenerationError(f"第 {index} 个方案的 {field} 过长")
    return value


def _required_integer(option: dict, field: str, index: int, minimum: int, maximum: int) -> int:
    value = option.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise ThemeGenerationError(
            f"第 {index} 个方案的 {field} 必须是 {minimum} 到 {maximum} 的整数"
        )
    return value


def _safe_id(raw_id: object, option: dict, index: int, used: set[str]) -> str:
    candidate = raw_id.strip() if isinstance(raw_id, str) else ""
    if _SLUG_RE.fullmatch(candidate) and candidate not in used:
        return candidate
    digest_source = json.dumps(option, ensure_ascii=False, sort_keys=True) + f":{index}"
    digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:10]
    candidate = f"story-{digest}"
    counter = 2
    while candidate in used:
        candidate = f"story-{digest}-{counter}"
        counter += 1
    return candidate


def parse_theme_response(content: str) -> list[dict]:
    """Strictly parse and normalize a model response into exactly three options."""
    if not isinstance(content, str) or not content.strip():
        raise ThemeGenerationError("主题构思模型返回了空内容")
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ThemeGenerationError(f"主题构思模型返回的 JSON 无效: {exc.msg}") from exc
    if not isinstance(payload, dict) or set(payload) != {"options"}:
        raise ThemeGenerationError("主题构思 JSON 顶层必须只包含 options")
    options = payload["options"]
    if not isinstance(options, list) or len(options) != 3:
        raise ThemeGenerationError("主题构思必须返回恰好 3 个方案")

    normalized = []
    used_ids: set[str] = set()
    required_fields = {
        "title", "id", "genre", "description", "chapter_count",
        "words_per_chapter", "theme", "conflict",
    }
    for index, option in enumerate(options, 1):
        if not isinstance(option, dict) or set(option) != required_fields:
            raise ThemeGenerationError(f"第 {index} 个方案字段不完整或包含未知字段")
        novel_id = _safe_id(option["id"], option, index, used_ids)
        used_ids.add(novel_id)
        normalized.append({
            "title": _required_text(option, "title", index, 200),
            "id": novel_id,
            "genre": _required_text(option, "genre", index, 100),
            "description": _required_text(option, "description", index, 2000),
            "chapter_count": _required_integer(option, "chapter_count", index, 1, 100000),
            "words_per_chapter": _required_integer(option, "words_per_chapter", index, 1, 1000000),
            "theme": _required_text(option, "theme", index, 500),
            "conflict": _required_text(option, "conflict", index, 1000),
        })
    return normalized


def generate_themes(inspiration: str = "", genre: str = "", *, client=None,
                    environ: Mapping[str, str] | None = None) -> list[dict]:
    """Generate three novel concepts without reading or creating any novel workspace."""
    api_key, base_url, model = _configuration(os.environ if environ is None else environ)
    inspiration = inspiration.strip()
    genre = genre.strip()
    prompt = (
        "请为一部全新的中文长篇小说构思三个差异明显、可持续展开的方案。"
        "三个方案在主角目标、世界设定和核心矛盾上不得雷同。"
        "返回 JSON 对象，且只能包含 options 数组；数组必须恰好三个对象。"
        "每个对象必须且只能包含 title、id、genre、description、chapter_count、"
        "words_per_chapter、theme、conflict。id 使用小写英文字母、数字和连字符，"
        "chapter_count 与 words_per_chapter 使用整数。"
        f"\n用户灵感：{inspiration or '无，由你自由构思'}"
        f"\n题材偏好：{genre or '不限'}"
    )
    api_client = client or OpenAI(api_key=api_key, base_url=base_url)
    try:
        response = api_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是擅长长篇结构设计的中文小说策划编辑。只输出严格 JSON。"},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.9,
        )
        content = response.choices[0].message.content
    except Exception as exc:
        raise ThemeGenerationError(f"主题构思模型调用失败: {exc}") from exc
    return parse_theme_response(content)
