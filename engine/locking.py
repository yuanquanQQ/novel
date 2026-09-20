"""One reentrant, cross-process write lock per novel, shared by CLI and HTTP."""
from contextlib import contextmanager
from pathlib import Path
import os
import threading

_local = threading.local()


class NovelBusyError(RuntimeError):
    pass


@contextmanager
def novel_lock(root):
    root = Path(root).resolve()
    key = os.path.normcase(str(root))
    held = getattr(_local, "held", None)
    if held is None:
        held = _local.held = set()
    if key in held:
        yield
        return
    directory = root.parent / ".locks"
    directory.mkdir(parents=True, exist_ok=True)
    # Keep the lock file outside the book, so restore/delete cannot replace it.
    with (directory / (root.name + ".lock")).open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise NovelBusyError(f"小说 {root.name} 正被其他进程操作，请稍后重试") from exc
        held.add(key)
        try:
            yield
        finally:
            held.remove(key)
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)
