"""持久化任务执行器：子进程运行 novel.py，SSE 回传日志，每本小说串行。"""
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / "runtime" / "tasks"
MAX_LOG_LINES = 5000
TERMINAL_STATUSES = {"done", "failed", "error", "orphaned", "cancelled"}

_TASKS: dict = {}
_LOCKS: dict = {}
_GUARD = threading.RLock()


class BusyError(Exception):
    pass


def _atomic_text(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=path.name + ".", suffix=".tmp",
                                     delete=False) as handle:
        handle.write(content)
        temp_name = handle.name
    os.replace(temp_name, path)


def _state_view(t: dict) -> dict:
    return {key: value for key, value in t.items()
            if key not in {"lines", "_proc", "cancel_requested"}}


def _persist(t: dict):
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_text(TASKS_DIR / f"{t['id']}.json",
                 json.dumps(_state_view(t), ensure_ascii=False, indent=2))
    _atomic_text(TASKS_DIR / f"{t['id']}.log", "".join(t.get("lines", [])))


def _append(t: dict, line: str):
    with _GUARD:
        t.setdefault("lines", []).append(line)
        if len(t["lines"]) > MAX_LOG_LINES:
            del t["lines"][:-MAX_LOG_LINES]
        _persist(t)


def _set(t: dict, **changes):
    with _GUARD:
        t.update(changes)
        _persist(t)


def _load_history():
    with _GUARD:
        _TASKS.clear()
        _LOCKS.clear()
        if not TASKS_DIR.exists():
            return
        for state_path in TASKS_DIR.glob("*.json"):
            try:
                t = json.loads(state_path.read_text(encoding="utf-8"))
                log_path = TASKS_DIR / f"{t['id']}.log"
                lines = (log_path.read_text(encoding="utf-8").splitlines(keepends=True)
                         if log_path.exists() else [])[-MAX_LOG_LINES:]
                t["lines"] = lines
                t["_proc"] = None
                t["cancel_requested"] = False
                if t.get("status") == "running":
                    t["status"] = "orphaned"
                    t["pid"] = None
                    lines.append("[系统] 服务重启，原运行任务已标记为 orphaned。\n")
                    t["lines"] = lines[-MAX_LOG_LINES:]
                    _persist(t)
                _TASKS[t["id"]] = t
            except (OSError, ValueError, KeyError, TypeError):
                continue


def running_task(novel: str):
    with _GUARD:
        tid = _LOCKS.get(novel)
        if tid and tid in _TASKS:
            return tid
    return None


def submit(novel: str, action: str, args: list[str], steps: list[dict] | None = None) -> str:
    if steps is None:
        steps = [{"action": action, "args": list(args)}]
    with _GUARD:
        tid = _LOCKS.get(novel)
        if tid and tid in _TASKS:
            raise BusyError(f"小说 {novel} 已有任务在跑，请等待完成")
        new_id = uuid.uuid4().hex[:12]
        task = {
            "id": new_id, "novel": novel, "action": action, "args": list(args),
            "steps": steps, "status": "running", "lines": [], "done_steps": 0,
            "started": time.time(), "finished": None, "pid": None,
            "_proc": None, "cancel_requested": False,
        }
        _TASKS[new_id] = task
        _LOCKS[novel] = new_id
        _persist(task)
    threading.Thread(target=_worker, args=(new_id,), daemon=True).start()
    return new_id


def _run_step(t: dict, cmd: list[str]) -> int:
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    _append(t, "$ " + " ".join(cmd) + "\n")
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        cmd, cwd=str(ROOT), env=env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **kwargs)
    with _GUARD:
        t["_proc"] = proc
        t["pid"] = proc.pid
        _persist(t)
        should_cancel = t.get("cancel_requested", False)
    if should_cancel:
        _terminate_process_tree(proc.pid, proc)
    try:
        for raw in iter(proc.stdout.readline, b""):
            _append(t, raw.decode("utf-8", "replace").rstrip("\r\n") + "\n")
        return proc.wait()
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass
        with _GUARD:
            t["_proc"] = None
            t["pid"] = None
            _persist(t)


def _terminate_process_tree(pid: int, proc=None):
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=False)
    else:
        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            if proc is not None:
                proc.terminate()


def cancel(tid: str):
    with _GUARD:
        t = _TASKS.get(tid)
        if not t:
            return None
        if t.get("status") != "running":
            return {"id": tid, "status": t.get("status"), "cancelled": False}
        t["cancel_requested"] = True
        proc = t.get("_proc")
        pid = t.get("pid")
        _persist(t)
    if pid:
        _terminate_process_tree(pid, proc)
    with _GUARD:
        if t.get("status") == "running":
            t["status"] = "cancelled"
            t["finished"] = time.time()
            _append(t, "[取消] 任务已取消。\n")
    return {"id": tid, "status": t["status"], "cancelled": True}


def _worker(tid: str):
    t = _TASKS[tid]
    steps = t["steps"]
    total = len(steps)
    try:
        for i, step in enumerate(steps, 1):
            if t.get("cancel_requested"):
                _set(t, status="cancelled")
                return
            if total > 1:
                _append(t, f"━━ 步骤 {i}/{total}：{step['action']} {' '.join(step.get('args', []))} ━━\n")
            cmd = [sys.executable, "-u", str(ROOT / "novel.py"),
                   "--novel", t["novel"], step["action"], *step.get("args", [])]
            rc = _run_step(t, cmd)
            _set(t, done_steps=i)
            if t.get("cancel_requested") or t.get("status") == "cancelled":
                _set(t, status="cancelled")
                return
            if rc != 0:
                if total > 1 and i < total:
                    _append(t, f"[停止] 第 {i} 步失败（exit {rc}），剩余 {total - i} 步未执行\n")
                _set(t, status="failed")
                return
        _set(t, status="done")
    except Exception as exc:
        _append(t, f"[运行异常] {exc}\n")
        _set(t, status="cancelled" if t.get("cancel_requested") else "error")
    finally:
        _set(t, finished=time.time(), pid=None)
        _release(t)


def _release(t):
    with _GUARD:
        if _LOCKS.get(t["novel"]) == t["id"]:
            _LOCKS.pop(t["novel"], None)
        _persist(t)


def get(tid: str):
    return _TASKS.get(tid)


def list_tasks(novel: str = None):
    out = []
    with _GUARD:
        tasks = list(_TASKS.values())
    for t in tasks:
        if novel and t["novel"] != novel:
            continue
        out.append({
            "id": t["id"], "novel": t["novel"], "action": t["action"],
            "args": t["args"], "status": t["status"],
            "steps": len(t.get("steps", [])), "done_steps": t.get("done_steps", 0),
            "started": t.get("started"), "finished": t.get("finished"),
            "pid": t.get("pid"), "n_lines": len(t.get("lines", [])),
        })
    return sorted(out, key=lambda item: item["started"] or 0, reverse=True)


async def events(tid: str):
    import asyncio
    t = _TASKS.get(tid)
    if not t:
        return
    idx = 0
    while True:
        with _GUARD:
            lines = list(t.get("lines", []))
            status = t.get("status")
        while idx < len(lines):
            yield lines[idx]
            idx += 1
        if status != "running":
            break
        await asyncio.sleep(0.3)
    yield f"__TASK_END__ {status}"


_load_history()
