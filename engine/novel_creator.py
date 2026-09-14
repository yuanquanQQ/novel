"""Create isolated novel workspaces without copying an existing novel."""

import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from engine.db import NovelDB
from engine.settings import NOVELS_DIR

_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")


class NovelCreationError(ValueError):
    """Invalid data supplied for a new novel."""


def validate_slug(novel_id: str) -> str:
    if not isinstance(novel_id, str) or not _SLUG_RE.fullmatch(novel_id):
        raise NovelCreationError("id 必须是安全 slug：仅允许小写字母、数字和连字符")
    return novel_id


def _validate_text(value: str, field: str, required: bool = False) -> str:
    if not isinstance(value, str) or (required and not value.strip()):
        raise NovelCreationError(f"{field} 不能为空")
    if len(value) > 10000:
        raise NovelCreationError(f"{field} 过长")
    return value.strip()


def _volume_config(chapter_count: int) -> dict:
    volumes = {}
    volume_count = min(4, chapter_count)
    for index in range(volume_count):
        start = index * chapter_count // volume_count + 1
        end = (index + 1) * chapter_count // volume_count
        volumes[f"volume_{index + 1}"] = {
            "name": f"第{index + 1}卷",
            "chapters": (start, end),
            "core_emotion": "推进、冲突、转折",
            "focus": "推进主线并发展人物关系",
        }
    return volumes


def _config_py(title: str, chapter_count: int, words_per_chapter: int, volumes: dict) -> str:
    return f'''"""Standalone configuration for this novel."""
import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


def _load_local_env() -> dict[str, str]:
    values = {{}}
    env_file = PROJECT_ROOT / ".env"
    if not env_file.is_file():
        return values
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\\\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


_LOCAL_ENV = _load_local_env()


def _env(name: str, default: str) -> str:
    return _LOCAL_ENV.get(name) or os.getenv(name) or default


@dataclass
class ModelConfig:
    provider: str = "deepseek"
    model_name: str = "deepseek-chat"
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 0.9
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0

@dataclass
class Config:
    api_key: str = field(default_factory=lambda: _env("API_KEY", _env("DEEPSEEK_API_KEY", "your-api-key-here")))
    base_url: str = field(default_factory=lambda: _env("API_BASE_URL", _env("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")))
    planner_model: ModelConfig = field(default_factory=lambda: ModelConfig(model_name=_env("PLANNER_MODEL", "deepseek-reasoner"), temperature=0.6))
    researcher_model: ModelConfig = field(default_factory=lambda: ModelConfig(model_name=_env("RESEARCHER_MODEL", "deepseek-reasoner"), temperature=0.15))
    writer_model: ModelConfig = field(default_factory=lambda: ModelConfig(model_name=_env("WRITER_MODEL", "deepseek-chat"), temperature=0.9, max_tokens=8192))
    immediate_reviewer_model: ModelConfig = field(default_factory=lambda: ModelConfig(model_name=_env("IMMEDIATE_REVIEWER_MODEL", "deepseek-chat"), temperature=0.15))
    heavy_reviewer_model: ModelConfig = field(default_factory=lambda: ModelConfig(model_name=_env("HEAVY_REVIEWER_MODEL", "deepseek-reasoner"), temperature=0.6))
    keeper_model: ModelConfig = field(default_factory=lambda: ModelConfig(model_name=_env("KEEPER_MODEL", "deepseek-chat"), temperature=0.15))
    archivist_model: ModelConfig = field(default_factory=lambda: ModelConfig(model_name=_env("ARCHIVIST_MODEL", "deepseek-chat"), temperature=0.15))
    foreshadowing_steward_model: ModelConfig = field(default_factory=lambda: ModelConfig(model_name=_env("FORESHADOWING_STEWARD_MODEL", "deepseek-reasoner"), temperature=0.6))
    reader_proxy_model: ModelConfig = field(default_factory=lambda: ModelConfig(model_name=_env("READER_PROXY_MODEL", "deepseek-chat"), temperature=0.15))
    marketer_model: ModelConfig = field(default_factory=lambda: ModelConfig(model_name=_env("MARKETER_MODEL", "deepseek-chat"), temperature=0.9, max_tokens=8192))
    story_title: str = {title!r}
    chapter_count: int = {chapter_count}
    words_per_chapter: int = {words_per_chapter}
    language: str = "zh-CN"
    volume_config: dict = field(default_factory=lambda: {volumes!r})
    bible_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "bible")
    generated_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "generated")
    cache_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "cache")
    immediate_review_max_retries: int = 3
    heavy_review_interval: int = 5
    max_retries: int = 3
    retry_delay: float = 2.0

config = Config()
'''


def _env_example() -> str:
    return '''# 复制为同目录的 .env，再填写本书使用的 API 配置和模型名称。
# .env 仅供本机使用，不要提交到 git。

# API_KEY 优先于 DEEPSEEK_API_KEY；二者任选其一。
API_KEY=your-api-key-here
DEEPSEEK_API_KEY=your-api-key-here
# API_BASE_URL 优先于 DEEPSEEK_BASE_URL。
API_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1

# 主题构思（新建小说前的全局主题生成使用；默认 deepseek-chat）
THEME_MODEL=deepseek-chat

# 各 Agent 使用的模型（可按本书单独调整）
PLANNER_MODEL=deepseek-reasoner
RESEARCHER_MODEL=deepseek-reasoner
WRITER_MODEL=deepseek-chat
IMMEDIATE_REVIEWER_MODEL=deepseek-chat
HEAVY_REVIEWER_MODEL=deepseek-reasoner
KEEPER_MODEL=deepseek-chat
ARCHIVIST_MODEL=deepseek-chat
FORESHADOWING_STEWARD_MODEL=deepseek-reasoner
READER_PROXY_MODEL=deepseek-chat
MARKETER_MODEL=deepseek-chat
'''


def _prompts(title: str, genre: str, description: str) -> dict:
    context = f"书名：《{title}》；类型：{genre or '未指定'}；简介：{description or '待创作'}"
    generic = "你是小说创作助手。请基于给定设定完成任务，保持人物和事实一致，直接输出结果。"
    return {
        "_meta": {"novel": title, "genre": genre, "description": description, "version": "1.0"},
        "planner": {"system": generic + "\n" + context, "chapter_template": "章节：{chapter_num}\n指令：{instruction}"},
        "outline_generator": {"system": generic + "\n请根据世界观、人物和分卷规划生成完整章节大纲。", "chapter_template": ""},
        "title_generator": {"system": generic + "\n请根据以下大纲生成章名并输出 JSON：\n{outline}", "chapter_template": ""},
        "volume_summary": {"system": generic + "\n请总结{volume_name}（第{vol_start}-{vol_end}章）。\n核心情绪：{volume_emotion}\n章节摘要：\n{chapter_summaries}", "chapter_template": ""},
        "researcher": {"system": generic, "chapter_template": "章节计划：{plan_json}\n知识库：{search_results}"},
        "writer": {"system": generic + "\n请写出自然、具体的中文小说正文。"},
        "reviewer_immediate": {"system": generic + "请检查正文是否符合任务要求并输出 JSON。"},
        "reviewer_heavy": {"system": generic + "请审阅章节结构、事实一致性和可读性并输出 JSON。"},
        "dialogue_auditor": {"system": generic + "请审计人物对话声口并输出 JSON。"},
        "keeper": {"system": generic + "请把场景压缩成运行时上下文并输出 JSON。"},
        "archivist": {"system": generic + "请从章节信息提取事实并输出 JSON。"},
        "foreshadowing_steward": {"system": generic + "请检查线索生命周期并输出 JSON。"},
        "reader_proxy": {"system": generic + "请模拟读者反馈并输出 JSON。"},
        "marketer": {"synopsis": generic + "请写小说简介。", "teaser": generic + "请写章节推荐语。", "tags": generic + "请生成标签。", "author_note": generic + "请写作者的话。", "cover_art": generic + "请写封面提示词。", "character_portrait": generic + "请写人物立绘提示词。", "scene_illustration": generic + "请写场景插图提示词。"},
    }


def create_novel(id, title, chapter_count, words_per_chapter, genre, description):
    """Create a novel directory atomically and return its final path."""
    novel_id = validate_slug(id)
    title = _validate_text(title, "title", required=True)
    genre = _validate_text(genre, "genre")
    description = _validate_text(description, "description")
    if not isinstance(chapter_count, int) or isinstance(chapter_count, bool) or not 1 <= chapter_count <= 100000:
        raise NovelCreationError("chapter_count 必须是 1 到 100000 的整数")
    if not isinstance(words_per_chapter, int) or isinstance(words_per_chapter, bool) or not 1 <= words_per_chapter <= 1000000:
        raise NovelCreationError("words_per_chapter 必须是正整数")

    root = NOVELS_DIR.resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / novel_id
    if target.exists():
        raise FileExistsError(f"小说 id 已存在: {novel_id}")
    volumes = _volume_config(chapter_count)
    temp_dir = Path(tempfile.mkdtemp(prefix=f".{novel_id}-", dir=str(root)))
    try:
        (temp_dir / "bible").mkdir()
        (temp_dir / "generated").mkdir()
        (temp_dir / "cache").mkdir()
        (temp_dir / "config.py").write_text(_config_py(title, chapter_count, words_per_chapter, volumes), encoding="utf-8")
        (temp_dir / ".env.example").write_text(_env_example(), encoding="utf-8")
        (temp_dir / "novel_prompts.json").write_text(json.dumps(_prompts(title, genre, description), ensure_ascii=False, indent=2), encoding="utf-8")
        (temp_dir / "bible" / "master_bible.md").write_text(f"# {title}\n\n## 类型\n{genre}\n\n## 简介\n{description}\n", encoding="utf-8")
        (temp_dir / "bible" / "characters.json").write_text(json.dumps({"characters": {}}, ensure_ascii=False, indent=2), encoding="utf-8")
        (temp_dir / "bible" / "clues.json").write_text(json.dumps({"clues": {}, "active_foreshadowing": {}}, ensure_ascii=False, indent=2), encoding="utf-8")
        (temp_dir / "bible" / "motif_bank.json").write_text(json.dumps({"motifs": []}, ensure_ascii=False, indent=2), encoding="utf-8")
        (temp_dir / "bible" / "lessons_learned.jsonl").write_text("", encoding="utf-8")
        titles = {"_schema": "1.0", "_description": "章节标题库", "volumes": {}}
        for key, volume in volumes.items():
            lo, hi = volume["chapters"]
            titles["volumes"][key] = {"name": volume["name"], "range": [lo, hi], "synopsis": volume["focus"], "chapters": {str(n): f"第{n}章" for n in range(lo, hi + 1)}}
        (temp_dir / "bible" / "chapter_titles.json").write_text(json.dumps(titles, ensure_ascii=False, indent=2), encoding="utf-8")
        db = NovelDB(temp_dir)
        try:
            db.ensure_imported()
        finally:
            db.close()
        os.replace(str(temp_dir), str(target))
        return target
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
