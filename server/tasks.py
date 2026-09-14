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


def submit(novel: str, action: str, args: list[str]) -> str:
    with _GUARD:
        tid = _LOCKS.get(novel)
        if tid and _TASKS.get(tid, {}).get("status") == "running":
            raise BusyError(f"小说 {novel} 已有任务在跑，请等待完成")
        new_id = uuid.uuid4().hex[:12]
        _TASKS[new_id] = {"id": new_id, "novel": novel, "action": action,
                          "args": args, "status": "running", "lines": [],
                          "started": time.time()}
        _LOCKS[novel] = new_id
    threading.Thread(target=_worker, args=(new_id,), daemon=True).start()
    return new_id


def _worker(tid: str):
    t = _TASKS[tid]
    cmd = [sys.executable, "-u", str(ROOT / "novel.py"),
           "--novel", t["novel"], t["action"], *t["args"]]
    t["lines"].append("$ " + " ".join(cmd) + "\n")
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(ROOT), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
    except Exception as e:
        t["lines"].append(f"[启动失败] {e}\n")
        t["status"] = "error"
        _release(t)
        return
    try:
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip("\r\n") + "\n"
            t["lines"].append(line)
        rc = proc.wait()
        t["status"] = "done" if rc == 0 else "failed"
    except Exception as e:
        t["lines"].append(f"[运行异常] {e}\n")
        t["status"] = "error"
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass
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
