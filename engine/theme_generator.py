"""Generate standalone novel theme suggestions with an OpenAI-compatible API."""

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Mapping

from openai import OpenAI

from engine.env_loader import load_env

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"
THEME_DIRECTIONS = (
    "悬疑推理", "都市情感", "科幻未来", "奇幻冒险",
    "历史权谋", "成长热血", "惊悚生存", "自由创作",
)
CHANNELS = ("男频", "女频", "不限")
PROTAGONIST_GENDERS = ("男主角", "女主角", "双主角", "不限")
LENGTH_PRESETS = {
    "长篇200-400章": (200, 400),
    "超长篇500-800章": (500, 800),
    "巨长篇1000-1500章": (1000, 1500),
}
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


def _normalize_gender(value: str) -> str:
    compact = re.sub(r"[\s_\-（）()]+", "", value).casefold()
    aliases = {
        "男": "男主角", "男性": "男主角", "男主": "男主角", "男性主角": "男主角",
        "male": "男主角", "malelead": "男主角", "maleprotagonist": "男主角",
        "女": "女主角", "女性": "女主角", "女主": "女主角", "女性主角": "女主角",
        "female": "女主角", "femaleprotagonist": "女主角",
        "双主": "双主角", "双男主": "双主角", "双女主": "双主角", "双主人公": "双主角",
        "dual": "双主角", "dualprotagonists": "双主角",
        "不限": "不限", "任意": "不限", "不限制": "不限", "any": "不限",
    }
    return aliases.get(compact, value.strip())


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


def parse_theme_response(
    content: str,
    expected_gender: str = "男主角",
    chapter_range: tuple[int, int] = (200, 400),
) -> list[dict]:
    """Strictly parse and normalize a model response into exactly three options."""
    if expected_gender not in PROTAGONIST_GENDERS:
        raise ThemeGenerationError("请选择有效的主角类型")
    if (not isinstance(chapter_range, tuple) or len(chapter_range) != 2
            or not all(isinstance(value, int) for value in chapter_range)
            or chapter_range[0] > chapter_range[1]):
        raise ThemeGenerationError("章节范围无效")
    minimum_chapters, maximum_chapters = chapter_range
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
        "words_per_chapter", "theme", "conflict", "protagonist_name",
        "protagonist_gender",
    }
    for index, option in enumerate(options, 1):
        if not isinstance(option, dict) or set(option) != required_fields:
            raise ThemeGenerationError(f"第 {index} 个方案字段不完整或包含未知字段")
        novel_id = _safe_id(option["id"], option, index, used_ids)
        used_ids.add(novel_id)
        raw_gender = _required_text(option, "protagonist_gender", index, 20)
        option_gender = _normalize_gender(raw_gender)
        if expected_gender != "不限" and option_gender != expected_gender:
            raise ThemeGenerationError(
                f"第 {index} 个方案的主角类型为“{raw_gender}”，期望“{expected_gender}”"
            )
        if option_gender not in PROTAGONIST_GENDERS:
            raise ThemeGenerationError(f"第 {index} 个方案的主角类型“{raw_gender}”无效")
        normalized.append({
            "title": _required_text(option, "title", index, 200),
            "id": novel_id,
            "genre": _required_text(option, "genre", index, 100),
            "description": _required_text(option, "description", index, 2000),
            "chapter_count": _required_integer(option, "chapter_count", index, minimum_chapters, maximum_chapters),
            "words_per_chapter": _required_integer(option, "words_per_chapter", index, 1, 1000000),
            "theme": _required_text(option, "theme", index, 500),
            "conflict": _required_text(option, "conflict", index, 1000),
            "protagonist_name": _required_text(option, "protagonist_name", index, 100),
            "protagonist_gender": option_gender,
        })
    return normalized


def generate_themes(inspiration: str = "", genre: str = "", direction: str = "",
                    channel: str = "男频", protagonist_gender: str = "男主角",
                    length: str = "长篇200-400章", *, client=None,
                    environ: Mapping[str, str] | None = None) -> list[dict]:
    """Generate three novel concepts without reading or creating any novel workspace."""
    direction = direction.strip()
    if direction not in THEME_DIRECTIONS:
        raise ThemeGenerationError("请选择有效的主题方向")
    if channel not in CHANNELS:
        raise ThemeGenerationError("请选择有效的频道")
    if protagonist_gender not in PROTAGONIST_GENDERS:
        raise ThemeGenerationError("请选择有效的主角类型")
    if length not in LENGTH_PRESETS:
        raise ThemeGenerationError("请选择有效的篇幅")
    chapter_range = LENGTH_PRESETS[length]
    if environ is None:
        environ = load_env(root_path=Path(__file__).resolve().parent.parent / ".env")
    api_key, base_url, model = _configuration(environ)
    inspiration = inspiration.strip()
    genre = genre.strip()
    gender_instruction = (
        f"三个方案的 protagonist_gender 都必须逐字填写“{protagonist_gender}”；"
        "人物姓名、身份、经历和简介也必须与该主角类型一致。"
        if protagonist_gender != "不限" else
        "每个方案的 protagonist_gender 必须填写男主角、女主角或双主角之一，并与人物设定一致。"
    )
    prompt = (
        "请为一部全新的中文长篇小说构思三个差异明显、可持续展开的方案。"
        "三个方案在主角目标、世界设定和核心矛盾上不得雷同。"
        "返回 JSON 对象，且只能包含 options 数组；数组必须恰好三个对象。"
        "每个对象必须且只能包含 title、id、genre、description、chapter_count、"
        "words_per_chapter、theme、conflict、protagonist_name、protagonist_gender。"
        "id 使用小写英文字母、数字和连字符，chapter_count 与 words_per_chapter 使用整数。"
        f"\n频道：{channel}；目标主角类型：{protagonist_gender}。"
        f"{gender_instruction}"
        f"\n篇幅：{length}，chapter_count 必须严格在 {chapter_range[0]} 到 {chapter_range[1]} 章之间。"
        "必须面向频道受众，围绕主角持续升级、明确爽点、势力成长与多卷结构设计，"
        "保证冲突和能力体系可持续推进，禁止只适合短篇或四十余章的收束。"
        f"\n创作方向：{direction}（必须围绕此方向设计，不得偏离）"
        f"\n用户灵感：{inspiration or '无，由你自由构思'}"
        f"\n题材偏好：{genre or '不限'}"
    )
    api_client = client or OpenAI(api_key=api_key, base_url=base_url)
    validation_error = None
    for attempt in range(1, 4):
        retry_instruction = ""
        if validation_error is not None:
            retry_instruction = (
                f"\n上一轮返回未通过校验，具体错误：{validation_error}"
                "\n请重新生成完整响应，不要只修改单个方案；仍须返回恰好 3 个全部合格、"
                "字段完整且互不雷同的方案。"
            )
        try:
            response = api_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "你是擅长长篇结构设计的中文小说策划编辑。只输出严格 JSON。"},
                    {"role": "user", "content": prompt + retry_instruction},
                ],
                response_format={"type": "json_object"},
                temperature=0.9,
            )
            content = response.choices[0].message.content
        except Exception as exc:
            raise ThemeGenerationError(
                f"主题构思模型调用失败（第 {attempt} 轮）: {exc}"
            ) from exc
        try:
            return parse_theme_response(content, protagonist_gender, chapter_range)
        except ThemeGenerationError as exc:
            validation_error = exc

    raise ThemeGenerationError(
        f"主题构思模型连续 3 轮返回无效方案，最后错误：{validation_error}"
    ) from validation_error
