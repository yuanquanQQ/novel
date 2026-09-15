import re
from pathlib import Path


_CHAPTER_FILE_RE = re.compile(r"chapter_(\d+)\.md")


def parse_chapter_number(path: Path) -> int | None:
    match = _CHAPTER_FILE_RE.fullmatch(path.name)
    return int(match.group(1)) if match else None


def chapter_files(
    directory: Path,
    *,
    before_chapter: int | None = None,
    first_chapter: int | None = None,
    last_chapter: int | None = None,
    limit: int | None = None,
) -> list[Path]:
    if not directory.exists():
        return []

    numbered = []
    for path in directory.glob("chapter_*.md"):
        number = parse_chapter_number(path)
        if number is None:
            continue
        if before_chapter is not None and number >= before_chapter:
            continue
        if first_chapter is not None and number < first_chapter:
            continue
        if last_chapter is not None and number > last_chapter:
            continue
        numbered.append((number, path.name, path))

    paths = [path for _, _, path in sorted(numbered)]
    return paths[-limit:] if limit is not None else paths
