# 待人工修订队列 — 未通过全部质量闸门的章节暂存于此
# revision/chapter_<n>.md（草案正文）+ chapter_<n>.json（诊断）,
# 作家改完经 `publish N` 才进 generated/ 与知识库。

import json
import os
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path


def revision_dir(config) -> Path:
    """待修订目录。默认 generated 的兄弟目录 revision；config 显式提供则优先。"""
    return getattr(config, "revision_dir", config.generated_dir.parent / "revision")


def pending_path(config, num: int) -> Path:
    return revision_dir(config) / f"chapter_{num:02d}.md"


def diag_path(config, num: int) -> Path:
    return revision_dir(config) / f"chapter_{num:02d}.json"


def _atomic_write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp",
                                         delete=False) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temp_name = handle.name
        for attempt in range(5):
            try:
                os.replace(temp_name, path)
                temp_name = None
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.02 * (attempt + 1))
    finally:
        if temp_name:
            try:
                os.unlink(temp_name)
            except OSError:
                pass


def save_pending(config, num: int, full_chapter: str, diagnostics: dict):
    """把合并稿正文 + 诊断落 revision/。diagnostics 必须含 plan_json/keeper_cache。"""
    d = revision_dir(config)
    d.mkdir(parents=True, exist_ok=True)
    _atomic_write(d / f"chapter_{num:02d}.md", full_chapter)
    _atomic_write(d / f"chapter_{num:02d}.json",
                  json.dumps(diagnostics, ensure_ascii=False, indent=2))


def load_pending(config, num: int):
    """返回 {"content": md 文本, "diagnostics": diag dict}，队列中无该章返回 None。"""
    md, dj = pending_path(config, num), diag_path(config, num)
    if not md.is_file():
        return None
    diagnostics = None
    if dj.is_file():
        try:
            diagnostics = json.loads(dj.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            diagnostics = None
    return {"content": md.read_text(encoding="utf-8"), "diagnostics": diagnostics}


def remove_pending(config, num: int) -> bool:
    """删除该章待修订文件；删掉任何文件返回 True，队列本无则 False。"""
    removed = False
    for fp in (pending_path(config, num), diag_path(config, num)):
        try:
            fp.unlink()
            removed = True
        except FileNotFoundError:
            pass
        except OSError:
            return False
    return removed


def list_pending(config) -> list:
    """按章号升序返回待修订队列项：{num, title, words, created_at, reasons}。"""
    d = revision_dir(config)
    if not d.is_dir():
        return []
    items = []
    for fp in sorted(d.glob("chapter_*.md")):
        match = re.fullmatch(r"chapter_(\d+)\.md", fp.name)
        if not match:
            continue
        num = int(match.group(1))
        diag = None
        dj = diag_path(config, num)
        if dj.is_file():
            try:
                diag = json.loads(dj.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                diag = None
        words = (diag or {}).get("words")
        if words is None:
            words = len(fp.read_text(encoding="utf-8"))
        items.append({
            "num": num,
            "title": (diag or {}).get("title", ""),
            "words": words,
            "created_at": (diag or {}).get("created_at", ""),
            "reasons": ((diag or {}).get("reasons") or {}) if diag else {},
        })
    items.sort(key=lambda item: item["num"])
    return items


def build_diagnostics(num: int, title: str, words: int, plan_json: dict,
                      keeper_cache: dict, scene_failures: list,
                      final_scan, style_hits: list) -> dict:
    """组装 diag JSON。keeper_cache 去除 bulky all_scenes，保留 archivist 所需的快照。"""
    cache = dict(keeper_cache)
    cache.pop("all_scenes", None)
    scan = getattr(final_scan, "metrics", {})
    final_scan_reasons = [
        {"category": item.get("category", ""), "pattern": item.get("pattern", ""),
         "count": item.get("count", 0), "where": item.get("where", ""),
         "hint": item.get("hint", "")}
        for item in (getattr(final_scan, "violations", []) or [])
        + (getattr(final_scan, "warnings", []) or [])
    ]
    return {
        "chapter": num,
        "title": title,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "words": words,
        "plan_json": plan_json,
        "keeper_cache": cache,
        "reasons": {
            "scene_failures": scene_failures,
            "final_scan": final_scan_reasons,
        },
        "scan_metrics": scan,
        "style_hits": style_hits or [],
    }
