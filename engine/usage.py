"""Per-command call budgets and content-free model usage records."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import json
import logging
import time
import uuid

log = logging.getLogger("usage")
_run = ContextVar("model_run", default=None)


class CallBudgetExceeded(RuntimeError):
    pass


def task_limit(config, action):
    explicit = getattr(config, "max_model_calls_per_task", None)
    if explicit is not None:
        return int(explicit)
    if action == "rebuild":
        from engine.chapter_files import chapter_files
        return max(120, 12 * len(chapter_files(config.generated_dir)))
    if action in ("outline", "titles"):
        return max(120, 12 * int(getattr(config, "chapter_count", 1)))
    return 120


@dataclass
class Run:
    root: object
    action: str
    limit: int
    id: str
    calls: int = 0


@contextmanager
def usage_run(root, action, limit=120):
    state = Run(root, action, max(1, int(limit)), uuid.uuid4().hex)
    token = _run.set(state)
    try:
        yield state
    finally:
        _run.reset(token)


def reserve_call():
    state = _run.get()
    if state is None:
        return
    if state.calls >= state.limit:
        raise CallBudgetExceeded(f"本次任务已达到 {state.limit} 次模型调用上限，已停止继续请求")
    state.calls += 1


def record_call(model, started, response=None, error=None):
    state = _run.get()
    if state is None:
        return
    usage = getattr(response, "usage", None)
    def count(key):
        value = usage.get(key) if isinstance(usage, dict) else getattr(usage, key, None)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
    entry = {"run_id": state.id, "action": state.action, "call": state.calls,
             "model": model, "seconds": round(time.monotonic() - started, 3),
             "prompt_tokens": count("prompt_tokens"), "completion_tokens": count("completion_tokens"),
             "total_tokens": count("total_tokens"), "error_type": type(error).__name__ if error else None}
    try:
        path = state.root / "cache/model_usage.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        log.warning("模型用量记录失败: %s", type(exc).__name__)
