"""每小说模型配置 — 读写 novels/<name>/.env（API Key / Base URL / 各 Agent 模型名）。

- .env 是唯一写入口：合并更新，绝不清空用户已有配置
- 白名单 key + 值校验（防注入）
- API Key 永不回传明文，只回传掩码
- 旧版内嵌模型的 config.py 支持一次性升级为 env 驱动（备份 .bak）
"""

import re
import sys
import time
from pathlib import Path

from engine.settings import NOVELS_DIR
from engine.env_loader import load_env, read_env_file as _read_env_file, root_env_path

ENV_API_KEY = "API_KEY"
ENV_BASE_URL = "API_BASE_URL"
ENV_THEME_MODEL = "THEME_MODEL"

# attr=Config 字段, env=环境变量名, label=前端显示, default=模板默认值, tier=建议档位
AGENT_ROLES = [
    {"attr": "planner_model", "env": "PLANNER_MODEL", "label": "Planner · 章节规划", "default": "deepseek-reasoner"},
    {"attr": "researcher_model", "env": "RESEARCHER_MODEL", "label": "Researcher · 资料检索", "default": "deepseek-reasoner"},
    {"attr": "writer_model", "env": "WRITER_MODEL", "label": "Writer · 正文撰写", "default": "deepseek-chat"},
    {"attr": "immediate_reviewer_model", "env": "IMMEDIATE_REVIEWER_MODEL", "label": "Reviewer · 即时审阅", "default": "deepseek-chat"},
    {"attr": "heavy_reviewer_model", "env": "HEAVY_REVIEWER_MODEL", "label": "Reviewer · 重型审阅", "default": "deepseek-reasoner"},
    {"attr": "keeper_model", "env": "KEEPER_MODEL", "label": "Keeper · 记忆压缩", "default": "deepseek-chat"},
    {"attr": "archivist_model", "env": "ARCHIVIST_MODEL", "label": "Archivist · 归档提取", "default": "deepseek-chat"},
    {"attr": "story_keeper_model", "env": "STORY_KEEPER_MODEL", "label": "Story Keeper · 故事状态", "default": "deepseek-chat"},
    {"attr": "foreshadowing_steward_model", "env": "FORESHADOWING_STEWARD_MODEL", "label": "Steward · 伏笔管家", "default": "deepseek-reasoner"},
    {"attr": "reader_proxy_model", "env": "READER_PROXY_MODEL", "label": "Reader · 读者模拟", "default": "deepseek-chat"},
    {"attr": "marketer_model", "env": "MARKETER_MODEL", "label": "Marketer · 宣传文案", "default": "deepseek-chat"},
]
ENV_BY_ATTR = {r["attr"]: r["env"] for r in AGENT_ROLES}
ALLOWED_ENVS = {ENV_API_KEY, ENV_BASE_URL, ENV_THEME_MODEL} | set(ENV_BY_ATTR.values())
_VALUE_RE = re.compile(r"^[^\r\n=]{1,200}$")

MODEL_CONFIG_DEFAULTS = {
    "chat_model": "deepseek-chat",
    "reasoner_model": "deepseek-reasoner",
    "base_url": "https://api.deepseek.com/v1",
}
QUICK_CHAT_TARGETS = [
    ENV_THEME_MODEL, "WRITER_MODEL", "IMMEDIATE_REVIEWER_MODEL", "KEEPER_MODEL",
    "ARCHIVIST_MODEL", "STORY_KEEPER_MODEL", "READER_PROXY_MODEL", "MARKETER_MODEL",
]
QUICK_REASONER_TARGETS = [
    "PLANNER_MODEL", "RESEARCHER_MODEL", "HEAVY_REVIEWER_MODEL",
    "FORESHADOWING_STEWARD_MODEL",
]


class ModelConfigError(ValueError):
    """Invalid model configuration input."""


# ------------------------------------------------------------------ env I/O
def env_path(novel_dir_: Path) -> Path:
    return Path(novel_dir_) / ".env"


def read_env_file(path: Path) -> dict:
    return _read_env_file(path)


def effective_env(novel_dir_: Path) -> dict[str, str]:
    return load_env(local_path=env_path(novel_dir_), root_path=root_env_path(NOVELS_DIR))


def update_env_file(path: Path, updates: dict) -> dict:
    """合并写入：替换已有键所在行、新键追加文末；空值跳过；绝不删除未涉及的键。"""
    updates = {k: v for k, v in updates.items() if v not in (None, "")}
    validate_updates(updates)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    remaining = dict(updates)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in remaining:
            lines[i] = f"{key}={remaining.pop(key)}"
    lines += [f"{k}={v}" for k, v in remaining.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return read_env_file(path)


def validate_updates(updates: dict):
    for key, value in updates.items():
        if key not in ALLOWED_ENVS:
            raise ModelConfigError(f"不支持的配置项: {key}")
        if not isinstance(value, str) or not _VALUE_RE.match(value.strip()):
            raise ModelConfigError(f"配置项 {key} 的值不合法（不允许换行/等号，1-200字符）")


def sanitize_input(raw: dict | None) -> dict:
    """把外部 dict（env 名或 attr 名混用作 key）归一为 {ENV_KEY: value}。空值忽略。"""
    if not isinstance(raw, dict):
        raise ModelConfigError("model_config 必须是对象")
    out = {}
    for key, value in raw.items():
        env_key = key.upper() if key.upper() in ALLOWED_ENVS else ENV_BY_ATTR.get(key)
        if env_key is None:
            raise ModelConfigError(f"不支持的配置项: {key}")
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if not isinstance(value, str):
            raise ModelConfigError(f"配置项 {env_key} 必须是字符串")
        out[env_key] = value.strip()
    validate_updates(out)
    return out


def expand_quick(quick: dict | None) -> dict:
    """创作表单的简化配置 → {ENV_KEY: value}。chat/reasoner 一键覆盖所有角色。"""
    if not quick:
        return {}
    if not isinstance(quick, dict):
        raise ModelConfigError("quick_models 必须是对象")
    out = {}
    if quick.get("api_key"):
        out[ENV_API_KEY] = quick["api_key"].strip()
    if quick.get("base_url"):
        out[ENV_BASE_URL] = quick["base_url"].strip()
    chat = (quick.get("chat_model") or "").strip()
    reasoner = (quick.get("reasoner_model") or "").strip()
    for env_key in QUICK_CHAT_TARGETS:
        if chat:
            out[env_key] = chat
    for env_key in QUICK_REASONER_TARGETS:
        if reasoner:
            out[env_key] = reasoner
    validate_updates(out)
    return out


# ------------------------------------------------------------ env support?
def _env_markers(path: Path):
    text = path.read_text(encoding="utf-8")
    return ("_load_local_env" in text) or ("_LOCAL_ENV" in text), text


def env_supported(novel_dir_: Path) -> bool:
    config_file = Path(novel_dir_) / "config.py"
    if not config_file.is_file():
        return False
    supported, _ = _env_markers(config_file)
    return supported


def upgrade_config(novel_dir_: Path, name: str) -> bool:
    """把旧版硬编码模型的 config.py 重写为 env 驱动版（保留书名字/卷结构等参数）。"""
    from engine.novel_creator import _config_py
    from engine.settings import load_config
    config_file = Path(novel_dir_) / "config.py"
    supported, _ = _env_markers(config_file)
    if supported:
        return False
    cfg = load_config(name)
    volumes = {k: dict(v) for k, v in cfg.volume_config.items()}
    config_file.rename(config_file.with_suffix(".py.bak"))
    config_file.write_text(
        _config_py(cfg.story_title, cfg.chapter_count, cfg.words_per_chapter, volumes),
        encoding="utf-8")
    return True


# ------------------------------------------------------------------- views
def _mask_key(key: str) -> str:
    if not key or key == "your-api-key-here":
        return ""
    visible = key[-4:] if len(key) > 8 else key[:2]
    return f"••••{visible}"


def _effective_key(cfg) -> str:
    return getattr(cfg, "api_key", "") or getattr(cfg, "deepseek_api_key", "") or ""


def get_view(name: str) -> dict:
    from engine.settings import load_config
    novel_dir_ = NOVELS_DIR / name
    env_file = env_path(novel_dir_)
    env = read_env_file(env_file)
    effective = effective_env(novel_dir_)
    cfg = load_config(name)
    supported = env_supported(novel_dir_)

    key_env = effective.get(ENV_API_KEY) or effective.get("DEEPSEEK_API_KEY")
    base = effective.get(ENV_BASE_URL) or effective.get("DEEPSEEK_BASE_URL") \
        or getattr(cfg, "base_url", None) or getattr(cfg, "deepseek_base_url", "")

    roles = []
    for role in AGENT_ROLES:
        cfg_attr = getattr(cfg, role["attr"], None)
        current = getattr(cfg_attr, "model_name", "") if cfg_attr else ""
        if not current:
            current = effective.get(role["env"]) or role["default"]
        roles.append({
            **{k: role[k] for k in ("attr", "env", "label", "default")},
            "model": current,
            "env_value": env.get(role["env"], ""),
        })
    return {
        "env_supported": supported,
        "has_env_file": env_file.is_file(),
        "api_key_masked": _mask_key(key_env or _effective_key(cfg)),
        "api_key_set": bool(key_env) or _effective_key(cfg) not in ("", "your-api-key-here"),
        "base_url": base,
        "theme_model": effective.get(ENV_THEME_MODEL, "deepseek-chat"),
        "roles": roles,
    }


def save(name: str, updates: dict) -> dict:
    """写入本书 .env；旧格式小说自动升级 config.py。updates 已 sanitize。"""
    novel_dir_ = NOVELS_DIR / name
    upgraded = upgrade_config(novel_dir_, name) if updates else False
    if updates:
        validate_updates(updates)
        update_env_file(env_path(novel_dir_), updates)
        from engine.settings import invalidate_config
        invalidate_config(name)
    return {"ok": True, "upgraded_config": upgraded, "written": sorted(updates),
            "view": get_view(name)}


# -------------------------------------------------------------------- test
def test_connection(novel_dir_: Path, model: str, api_key: str = "",
                    base_url: str = "") -> dict:
    env = effective_env(novel_dir_)
    if not api_key:
        api_key = env.get(ENV_API_KEY) or env.get("DEEPSEEK_API_KEY", "")
    if not base_url:
        base_url = env.get(ENV_BASE_URL) or env.get("DEEPSEEK_BASE_URL", "")
    if not api_key:
        return {"ok": False, "model": model, "error": "未配置 API Key（本书 .env、系统环境变量都没有）"}
    model = (model or "").strip()
    try:
        model = _model_config_for(novel_dir_, model)  # 允许传 "writer_model"/"WRITER_MODEL"/模型名
    except Exception:
        pass
    if not model:
        return {"ok": False, "error": "未指定测试模型"}
    from openai import OpenAI
    started = time.time()
    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=20, max_retries=0)
        completion = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "ping，请只回复两个字"}],
            max_tokens=8, temperature=0,
        )
        reply = (completion.choices[0].message.content or "").strip()
        return {"ok": True, "model": model, "latency_ms": int((time.time() - started) * 1000),
                "reply": reply[:20]}
    except Exception as exc:
        return {"ok": False, "model": model, "latency_ms": int((time.time() - started) * 1000),
                "error": str(exc)[:300]}


def _model_config_for(novel_dir_: Path, model: str) -> str:
    env = effective_env(novel_dir_)
    if model in ALLOWED_ENVS:
        return env.get(model, "")
    if model in ENV_BY_ATTR:
        return env.get(ENV_BY_ATTR[model], "")
    return model
