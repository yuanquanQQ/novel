# 小说引擎 — 动态配置
# 必须先调用 set_novel('小说名')，再导入任何 Agent

import importlib.util
import sys
import uuid
from pathlib import Path

from engine.env_loader import read_env_file, root_env_path

ENGINE_ROOT = Path(__file__).resolve().parent.parent
NOVELS_DIR = ENGINE_ROOT / "novels"

_current_novel = None
_config = None


def set_novel(name: str):
    global _current_novel, _config
    novel_dir = NOVELS_DIR / name
    if not novel_dir.exists():
        raise FileNotFoundError(f"小说目录不存在: {novel_dir}")
    _current_novel = name
    _config = None
    novel_path = str(novel_dir)
    if novel_path not in sys.path:
        sys.path.insert(0, novel_path)
    from engine.prompts_loader import reload as reload_prompts
    reload_prompts()


def load_config(name: str):
    root = NOVELS_DIR.resolve()
    novel_dir = (root / name).resolve()
    if novel_dir.parent != root or not novel_dir.is_dir():
        raise FileNotFoundError(f"小说目录不存在: {novel_dir}")
    config_file = novel_dir / "config.py"
    if not config_file.is_file():
        raise FileNotFoundError(f"小说配置不存在: {config_file}")
    module_name = f"_novel_config_{name.encode('utf-8').hex()}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, config_file)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载小说配置: {config_file}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    config = module.config
    local_env = read_env_file(novel_dir / ".env")
    root_env = read_env_file(root_env_path(root))
    for keys, attr in ((
        ("API_KEY", "DEEPSEEK_API_KEY"), "api_key"),
        (("API_BASE_URL", "DEEPSEEK_BASE_URL"), "base_url"),
    ):
        if not any(key in local_env for key in keys) and hasattr(config, attr):
            for key in keys:
                if root_env.get(key):
                    setattr(config, attr, root_env[key])
                    break
    for attr in (
        "planner_model", "researcher_model", "writer_model", "immediate_reviewer_model",
        "heavy_reviewer_model", "keeper_model", "archivist_model",
        "foreshadowing_steward_model", "reader_proxy_model", "marketer_model",
    ):
        key = attr.upper()
        if key in local_env or key not in root_env:
            continue
        model_config = getattr(config, attr, None)
        if model_config is not None and hasattr(model_config, "model_name"):
            model_config.model_name = root_env[key]
    return config


def get_novel() -> str:
    if _current_novel is None:
        raise RuntimeError("未设置小说。请先调用 set_novel('小说名')")
    return _current_novel


def get_novel_dir() -> Path:
    return NOVELS_DIR / get_novel()


def invalidate_config(name: str | None = None):
    """丢弃缓存配置，确保本书 .env 的更新立即生效。"""
    global _config
    if name is None or name == _current_novel:
        _config = None


def get_config():
    global _config
    if _config is None:
        if _current_novel is None:
            raise RuntimeError("未设置小说。请先 set_novel('小说名') 再导入 Agent")
        _config = load_config(_current_novel)
    return _config
