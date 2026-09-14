# 配置文件 — API Key / 模型参数 / 小说设置
#
# API Key 优先级：环境变量 > .env 文件 > 此处默认值

import os
from pathlib import Path
from dataclasses import dataclass, field

try:
    PROJECT_ROOT = Path(__file__).resolve().parent
except NameError:
    PROJECT_ROOT = Path(os.getcwd())

_env_file = PROJECT_ROOT / ".env"
if _env_file.exists():
    for line in _env_file.read_text(encoding="utf-8-sig").split("\n"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def _get_api_key() -> str:
    return os.getenv("API_KEY", os.getenv("DEEPSEEK_API_KEY", "your-api-key-here"))


WRITER_TEMP = 0.90
WRITER_TOP_P = 0.9
LOGIC_TEMP = 0.60
EXTRACT_TEMP = 0.15


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
    # === API（本地模型） ===
    api_key: str = field(default_factory=lambda: os.getenv("API_KEY", "not-needed"))
    base_url: str = field(default_factory=lambda: os.getenv(
        "API_BASE_URL", "http://localhost:3001/v1"
    ))

    # === 模型分配（auto 自动路由） ===
    planner_model: ModelConfig = field(default_factory=lambda: ModelConfig(
        model_name="auto", temperature=LOGIC_TEMP
    ))
    researcher_model: ModelConfig = field(default_factory=lambda: ModelConfig(
        model_name="auto", temperature=EXTRACT_TEMP
    ))
    writer_model: ModelConfig = field(default_factory=lambda: ModelConfig(
        model_name="auto", temperature=WRITER_TEMP,
        top_p=WRITER_TOP_P, max_tokens=8192
    ))
    immediate_reviewer_model: ModelConfig = field(default_factory=lambda: ModelConfig(
        model_name="auto", temperature=EXTRACT_TEMP
    ))
    heavy_reviewer_model: ModelConfig = field(default_factory=lambda: ModelConfig(
        model_name="auto", temperature=LOGIC_TEMP
    ))
    keeper_model: ModelConfig = field(default_factory=lambda: ModelConfig(
        model_name="auto", temperature=EXTRACT_TEMP
    ))
    archivist_model: ModelConfig = field(default_factory=lambda: ModelConfig(
        model_name="auto", temperature=EXTRACT_TEMP
    ))

    # === 小说参数 ===
    story_title: str = "万古长青"
    chapter_count: int = 200
    words_per_chapter: int = 3000
    language: str = "zh-CN"
    volume_config: dict = field(default_factory=lambda: {
        "volume_1": {
            "name": "重生归来",
            "chapters": (1, 50),
            "core_emotion": "热血、碾压、畅快",
            "focus": "仙帝重生少年身，横扫宗门、碾压天才、收服旧部",
        },
        "volume_2": {
            "name": "威震九州",
            "chapters": (51, 100),
            "core_emotion": "震撼、敬畏、无敌",
            "focus": "九州扬名，各大势力臣服，揭开万年前陨落真相",
        },
        "volume_3": {
            "name": "诸天之上",
            "chapters": (101, 150),
            "core_emotion": "燃、热血、柔情",
            "focus": "飞升上界，对抗仙界巨头，找回前世挚爱",
        },
        "volume_4": {
            "name": "万古长青",
            "chapters": (151, 200),
            "core_emotion": "巅峰、释然、永恒",
            "focus": "终极之战，诸天归一，开创永恒纪元",
        },
    })

    # === 路径 ===
    bible_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "bible")
    generated_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "generated")
    cache_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "cache")

    # === 审阅 ===
    immediate_review_max_retries: int = 3
    heavy_review_interval: int = 5


config = Config()
