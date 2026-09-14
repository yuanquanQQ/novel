"""任务执行器：线程 + subprocess.Popen 跑 novel.py，SSE 轮询式回传日志。每本小说串行锁。"""
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_TASKS: dict = {}
_LOCKS: dict = {}       # novel -> running task_id
_GUARD = threading.Lock()


class BusyError(Exception):
    pass


def running_task(novel: str):
    with _GUARD:
        tid = _LOCKS.get(novel)
    if tid and _TASKS.get(tid, {}).get("status") == "running":
        return tid
    return None


def submit(novel: str, action: str, args: list[str], steps: list[dict] | None = None) -> str:
    """steps: [{action, args}, ...] 顺序执行；给 steps 时 action/args 仅作展示汇总。"""
    if steps is None:
        steps = [{"action": action, "args": list(args)}]
    with _GUARD:
        tid = _LOCKS.get(novel)
        if tid and _TASKS.get(tid, {}).get("status") == "running":
            raise BusyError(f"小说 {novel} 已有任务在跑，请等待完成")
        new_id = uuid.uuid4().hex[:12]
        _TASKS[new_id] = {"id": new_id, "novel": novel, "action": action,
                          "args": args, "steps": steps, "status": "running",
                          "lines": [], "done_steps": 0, "started": time.time()}
        _LOCKS[novel] = new_id
    threading.Thread(target=_worker, args=(new_id,), daemon=True).start()
    return new_id


def _run_step(t: dict, cmd: list[str]) -> int:
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    t["lines"].append("$ " + " ".join(cmd) + "\n")
    proc = subprocess.Popen(
        cmd, cwd=str(ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )
    try:
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip("\r\n") + "\n"
            t["lines"].append(line)
        return proc.wait()
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass


def _worker(tid: str):
    t = _TASKS[tid]
    steps = t["steps"]
    total = len(steps)
    try:
        for i, step in enumerate(steps, 1):
            if total > 1:
                mark = f"━━ 步骤 {i}/{total}：{step['action']} {' '.join(step.get('args', []))} ━━\n"
                t["lines"].append(mark)
            cmd = [sys.executable, "-u", str(ROOT / "novel.py"),
                   "--novel", t["novel"], step["action"], *step.get("args", [])]
            rc = _run_step(t, cmd)
            t["done_steps"] = i
            if rc != 0:
                if total > 1 and i < total:
                    t["lines"].append(f"[停止] 第 {i} 步失败（exit {rc}），剩余 {total - i} 步未执行\n")
                t["status"] = "failed"
                return
        t["status"] = "done"
    except Exception as e:
        t["lines"].append(f"[运行异常] {e}\n")
        t["status"] = "error"
    finally:
        _release(t)


def _release(t):
    with _GUARD:
        if _LOCKS.get(t["novel"]) == t["id"]:
            _LOCKS.pop(t["novel"], None)


def get(tid: str):
    return _TASKS.get(tid)


def list_tasks(novel: str = None):
    out = []
    for t in _TASKS.values():
        if novel and t["novel"] != novel:
            continue
        out.append({"id": t["id"], "novel": t["novel"], "action": t["action"],
                    "args": t["args"], "status": t["status"],
                    "steps": len(t.get("steps", [])), "done_steps": t.get("done_steps", 0),
                    "started": t["started"], "n_lines": len(t["lines"])})
    return sorted(out, key=lambda x: x["started"], reverse=True)


async def events(tid: str):
    """异步生成器：先补历史行，再轮询增量直到任务结束。"""
    import asyncio
    t = _TASKS.get(tid)
    if not t:
        return
    idx = 0
    while True:
        lines = t["lines"]
        while idx < len(lines):
            yield lines[idx]
            idx += 1
        if t["status"] != "running":
            break
        await asyncio.sleep(0.3)
    yield f"__TASK_END__ {t['status']}"
