# 配置文件 — API Key / 模型参数 / 小说设置
#
# API Key 优先级：环境变量 > .env 文件 > 此处默认值
# 推荐在同目录创建 .env 文件：DEEPSEEK_API_KEY=sk-xxx

import os
from pathlib import Path
from dataclasses import dataclass, field

# 项目根目录（本小说目录）
try:
    PROJECT_ROOT = Path(__file__).resolve().parent
except NameError:
    PROJECT_ROOT = Path(os.getcwd())

# 尝试加载 .env 文件
_env_file = PROJECT_ROOT / ".env"
if _env_file.exists():
    for line in _env_file.read_text(encoding="utf-8-sig").split("\n"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def _get_api_key() -> str:
    """API Key: 环境变量 > .env > 默认"""
    return os.getenv("DEEPSEEK_API_KEY", "your-api-key-here")

# 温度常量
WRITER_TEMP = 0.90
WRITER_TOP_P = 0.9
LOGIC_TEMP = 0.60
EXTRACT_TEMP = 0.15


@dataclass
class ModelConfig:
    """单个模型配置"""
    provider: str = "deepseek"
    model_name: str = "deepseek-chat"
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 0.9
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0


@dataclass
class Config:
    """全局配置"""
    # API 配置 — 三种方式设置密钥：
    #   1. 环境变量: set DEEPSEEK_API_KEY=sk-xxx
    #   2. .env 文件: 在 novels/mirror-city/.env 中写 DEEPSEEK_API_KEY=sk-xxx
    #   3. 直接改下面 _get_api_key() 函数的返回值
    deepseek_api_key: str = field(default_factory=_get_api_key)
    deepseek_base_url: str = field(default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"))

    # 模型分配 — v4pro 系列
    # deepseek-reasoner: 强逻辑推理，做大纲与伏笔推演、全章深层审查
    # deepseek-chat:     灵活对话，做撰写/信息压缩/格式检查/归档
    planner_model: ModelConfig = field(default_factory=lambda: ModelConfig(
        model_name="deepseek-reasoner", temperature=LOGIC_TEMP
    ))
    researcher_model: ModelConfig = field(default_factory=lambda: ModelConfig(
        model_name="deepseek-reasoner", temperature=EXTRACT_TEMP
    ))
    writer_model: ModelConfig = field(default_factory=lambda: ModelConfig(
        model_name="deepseek-chat", temperature=WRITER_TEMP,
        top_p=WRITER_TOP_P, max_tokens=8192
    ))
    immediate_reviewer_model: ModelConfig = field(default_factory=lambda: ModelConfig(
        model_name="deepseek-chat", temperature=EXTRACT_TEMP
    ))
    heavy_reviewer_model: ModelConfig = field(default_factory=lambda: ModelConfig(
        model_name="deepseek-reasoner", temperature=LOGIC_TEMP
    ))
    keeper_model: ModelConfig = field(default_factory=lambda: ModelConfig(
        model_name="deepseek-chat", temperature=EXTRACT_TEMP
    ))
    archivist_model: ModelConfig = field(default_factory=lambda: ModelConfig(
        model_name="deepseek-chat", temperature=EXTRACT_TEMP
    ))

    # 小说参数
    story_title: str = "镜影迷城"
    chapter_count: int = 210
    words_per_chapter: int = 3000
    language: str = "zh-CN"
    volume_config: dict = field(default_factory=lambda: {
        "volume_1": {"name": "镜影初醒", "chapters": (1, 50),
                     "core_emotion": "迷茫、恐惧、好奇",
                     "focus": "能力觉醒 + 个人小案 + 世界观揭开"},
        "volume_2": {"name": "影潮涌动", "chapters": (51, 110),
                     "core_emotion": "紧张、背叛、羁绊加深",
                     "focus": "势力登场 + 中型冲突 + 团队组建"},
        "volume_3": {"name": "镜界裂痕", "chapters": (111, 160),
                     "core_emotion": "震撼、绝望、希望交织",
                     "focus": "大规模冲突 + 身世挖掘 + 情感撕扯"},
        "volume_4": {"name": "镜我归一", "chapters": (161, 210),
                     "core_emotion": "燃、释怀、温暖",
                     "focus": "终极真相 + 决战 + 收束"},
    })

    # 路径 (相对于项目根目录)
    bible_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "bible")
    generated_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "generated")
    cache_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "cache")
    vector_db_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "vector_db")

    # 向量库
    chroma_collection_name: str = "jingying_micheng"
    embedding_model: str = "text-embedding-3-small"

    # 审阅阈值
    immediate_review_max_retries: int = 3
    heavy_review_interval: int = 5        # 每 N 章触发一次 Heavy Review

    # 重试
    max_retries: int = 3
    retry_delay: float = 2.0


config = Config()
