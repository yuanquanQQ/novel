"""Read-only loading of project and per-novel dotenv configuration."""

import os
from pathlib import Path
from typing import Mapping


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    path = Path(path)
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load_env(*, local_path: Path | None = None, root_path: Path | None = None,
             environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return merged config without modifying ``os.environ``.

    More specific sources win: local novel file, project root file, process env.
    """
    values: dict[str, str] = {}
    if environ is None:
        environ = os.environ
    values.update(environ)
    if root_path is not None:
        values.update(read_env_file(Path(root_path)))
    if local_path is not None:
        values.update(read_env_file(Path(local_path)))
    return values


def root_env_path(novels_dir: Path) -> Path:
    return Path(novels_dir).resolve().parent / ".env"
