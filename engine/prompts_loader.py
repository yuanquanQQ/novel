# 统一提示词加载器
# 从当前小说的 novel_prompts.json 加载所有提示词
# 支持 style_kit 共享 token：[STYLE_FORBIDDEN] [STYLE_TECHNIQUES] [STYLE_TOMATO]

import json
from pathlib import Path

_cache = None
_novel_dir = None
_style_cache = {}


def _init():
    global _novel_dir, _cache
    if _novel_dir is None:
        from engine.settings import get_novel_dir
        _novel_dir = get_novel_dir()
    if _cache is None:
        fp = _novel_dir / "novel_prompts.json"
        _cache = json.loads(fp.read_text(encoding="utf-8"))
    return _cache


def _style_file(fname: str) -> str:
    if fname not in _style_cache:
        from pathlib import Path as _P
        root = _P(__file__).resolve().parent / "style_kit"
        _style_cache[fname] = (root / fname).read_text(encoding="utf-8")
    return _style_cache[fname]


def _banned_words_inline() -> str:
    """把 banned_words.json 压成一行提示词用的禁用串。"""
    if "_banned" not in _style_cache:
        import json as _j
        from pathlib import Path as _P
        p = _P(__file__).resolve().parent / "style_kit" / "banned_words.json"
        rules = _j.loads(p.read_text(encoding="utf-8"))
        hw = "、".join(rules.get("hard_words", []))
        sw = "、".join(f"{k}(≤{v})" for k, v in rules.get("soft_words", {}).items())
        pat_ids = [pp.get("id", "") for pp in rules.get("patterns", [])
                   if pp.get("severity") == "hard"]
        _style_cache["_banned"] = (f"硬禁用词（命中即打回）：{hw}\n"
                                   f"软禁用词（超频次打回）：{sw}\n"
                                   f"高危句式ID：{ '、'.join(pat_ids) }（不是而是/破折号/反问式解说腔等）")
    return _style_cache["_banned"]


def _apply_style_tokens(text: str) -> str:
    if not text:
        return text
    return (text
            .replace("[STYLE_TECHNIQUES]", _style_file("techniques.md"))
            .replace("[STYLE_TOMATO]", _style_file("tomato_rules.md"))
            .replace("[STYLE_FORBIDDEN]", _banned_words_inline()))


def get_prompt(name: str):
    prompts = _init()
    entry = prompts.get(name, {})
    if "system" in entry or "chapter_template" in entry:
        return (_apply_style_tokens(entry.get("system", "")),
                _apply_style_tokens(entry.get("chapter_template", "")))
    if isinstance(entry, dict):
        return {k: _apply_style_tokens(str(v)) for k, v in entry.items()}, ""
    return _apply_style_tokens(str(entry)), ""


def get_meta():
    return _init().get("_meta", {})


def reload():
    global _cache, _novel_dir, _style_cache
    _cache = None
    _novel_dir = None
    _style_cache = {}
