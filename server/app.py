"""小说创作引擎 — Web 控制台后端 (FastAPI)"""
import io
import json
import os
import re
import shutil
import sqlite3
import stat
import sys
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.chapter_files import chapter_files, parse_chapter_number  # noqa: E402
from engine.settings import NOVELS_DIR, load_config  # noqa: E402
from engine.novel_creator import (  # noqa: E402
    NovelCreationError,
    _config_py,
    _resolve_model_env,
    create_novel,
    validate_slug,
)
from engine.theme_generator import (  # noqa: E402
    CHANNELS,
    LENGTH_PRESETS,
    PROTAGONIST_GENDERS,
    THEME_DIRECTIONS,
    ThemeConfigurationError,
    ThemeGenerationError,
    generate_themes,
)
from engine import model_config  # noqa: E402
from engine import pending  # noqa: E402
from engine.db import NovelDB  # noqa: E402
from engine.style_kit import scanner  # noqa: E402
from server import tasks as T  # noqa: E402
import novel as novel_cli  # noqa: E402

app = FastAPI(title="Novel Console API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:11451", "http://127.0.0.1:11451"],
    allow_methods=["*"], allow_headers=["*"])


def novel_dir(name: str) -> Path:
    root = NOVELS_DIR.resolve()
    if ".." in Path(name).parts:
        raise HTTPException(404, f"小说不存在: {name}")
    d = (root / name).resolve()
    if d.parent != root or not d.is_dir():
        raise HTTPException(404, f"小说不存在: {name}")
    return d


@contextmanager
def novel_operation(name: str):
    from engine.locking import novel_lock, NovelBusyError
    root = NOVELS_DIR.resolve()
    target = (root / name).resolve()
    if target.parent != root:
        raise HTTPException(404, "无效的小说路径")
    try:
        with T.novel_guard(name), novel_lock(target):
            yield
    except (T.BusyError, NovelBusyError) as exc:
        raise HTTPException(409, "该小说已有任务或操作运行中") from exc


def _atomic_write_text(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=path.name + ".", suffix=".tmp",
                                     delete=False) as handle:
        handle.write(content)
        temp_name = handle.name
    try:
        os.replace(temp_name, path)
    except Exception:
        Path(temp_name).unlink(missing_ok=True)
        raise


@app.get("/api/novels/{name}/export")
def api_export_novel(name: str):
    try:
        validate_slug(name)
    except NovelCreationError as exc:
        raise HTTPException(404, f"小说不存在: {name}") from exc
    d = novel_dir(name)
    archive = io.BytesIO()
    top_files = {"novel_prompts.json", "config.py", ".env.example"}
    excluded = {".env", "db", "cache", "vector_db", "__pycache__"}
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in d.rglob("*"):
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(d)
            if relative.parts[0] in excluded:
                continue
            if len(relative.parts) == 1 and relative.name not in top_files:
                continue
            if len(relative.parts) > 1 and relative.parts[0] not in {"bible", "generated"}:
                continue
            if any(part in excluded for part in relative.parts):
                continue
            zf.write(path, relative.as_posix())
    archive.seek(0)
    return StreamingResponse(
        archive, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}.zip"'})


MAX_BACKUP_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_BACKUP_FILES = 5000
MAX_BACKUP_FILE_BYTES = 100 * 1024 * 1024
MAX_BACKUP_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
BACKUP_METADATA_FILE = "backup_metadata.json"
_BACKUP_TOP_FILES = {BACKUP_METADATA_FILE, "novel_prompts.json", ".env.example"}
_BACKUP_IMPORT_TOP_FILES = _BACKUP_TOP_FILES | {"config.py"}
_BACKUP_DIRS = {"bible", "generated", "cache", "revision"}


def _backup_file_allowed(relative: Path) -> bool:
    parts = relative.parts
    if not parts or any(part == ".env" for part in parts):
        return False
    if len(parts) == 1:
        return parts[0] in _BACKUP_TOP_FILES and parts[0] != BACKUP_METADATA_FILE
    if parts[0] not in _BACKUP_DIRS:
        return False
    return not (parts[0] == "cache" and len(parts) > 1 and parts[1] == "failed_drafts")


def _backup_metadata(cfg) -> dict:
    return {
        "format_version": 1,
        "title": cfg.story_title,
        "chapter_count": cfg.chapter_count,
        "words_per_chapter": cfg.words_per_chapter,
        "language": getattr(cfg, "language", "zh-CN"),
        "volume_config": cfg.volume_config,
    }


def _validate_backup_metadata(data) -> dict:
    if not isinstance(data, dict) or data.get("format_version") != 1:
        raise HTTPException(400, "备份 metadata 格式或版本无效")
    title = data.get("title")
    chapter_count = data.get("chapter_count")
    words_per_chapter = data.get("words_per_chapter")
    volumes = data.get("volume_config")
    if not isinstance(title, str) or not title.strip() or len(title) > 10000:
        raise HTTPException(400, "备份 metadata 的 title 无效")
    if (not isinstance(chapter_count, int) or isinstance(chapter_count, bool)
            or not 1 <= chapter_count <= 100000):
        raise HTTPException(400, "备份 metadata 的 chapter_count 无效")
    if (not isinstance(words_per_chapter, int) or isinstance(words_per_chapter, bool)
            or not 1 <= words_per_chapter <= 1000000):
        raise HTTPException(400, "备份 metadata 的 words_per_chapter 无效")
    if not isinstance(volumes, dict) or not volumes:
        raise HTTPException(400, "备份 metadata 的 volume_config 无效")
    normalized = {}
    for key, volume in volumes.items():
        if not isinstance(key, str) or not isinstance(volume, dict):
            raise HTTPException(400, "备份 metadata 的分卷结构无效")
        chapters = volume.get("chapters")
        if (not isinstance(chapters, (list, tuple)) or len(chapters) != 2
                or not all(isinstance(value, int) and not isinstance(value, bool)
                           for value in chapters)
                or chapters[0] < 1 or chapters[0] > chapters[1]
                or chapters[1] > chapter_count):
            raise HTTPException(400, f"备份 metadata 的分卷范围无效: {key}")
        normalized[key] = dict(volume, chapters=tuple(chapters))
    return {"title": title.strip(), "chapter_count": chapter_count,
            "words_per_chapter": words_per_chapter, "volume_config": normalized}


@app.get("/api/novels/{name}/backup")
def api_backup_novel(name: str):
    try:
        validate_slug(name)
    except NovelCreationError as exc:
        raise HTTPException(404, f"小说不存在: {name}") from exc
    archive = io.BytesIO()
    try:
        with novel_operation(name):
            d = novel_dir(name)
            metadata = _backup_metadata(load_config(name))
            with tempfile.TemporaryDirectory() as temp_name:
                snapshot = Path(temp_name) / "novel.db"
                db_path = d / "db" / "novel.db"
                if db_path.is_file() and not db_path.is_symlink():
                    source = sqlite3.connect(str(db_path))
                    target = sqlite3.connect(str(snapshot))
                    try:
                        source.backup(target)
                    finally:
                        target.close()
                        source.close()
                with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
                    zf.writestr(BACKUP_METADATA_FILE,
                                json.dumps(metadata, ensure_ascii=False, indent=2))
                    for path in d.rglob("*"):
                        if path.is_symlink() or not path.is_file():
                            continue
                        relative = path.relative_to(d)
                        if _backup_file_allowed(relative):
                            zf.write(path, relative.as_posix())
                    if snapshot.exists():
                        zf.write(snapshot, "db/novel.db")
    except (OSError, sqlite3.Error, zipfile.BadZipFile) as exc:
        raise HTTPException(500, f"工作区备份失败: {exc}") from exc
    archive.seek(0)
    return StreamingResponse(
        archive, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}-workspace.zip"'})


def _validated_backup_members(zf: zipfile.ZipFile):
    infos = zf.infolist()
    if len(infos) > MAX_BACKUP_FILES:
        raise HTTPException(413, f"备份文件数量超过限制（{MAX_BACKUP_FILES}）")
    members = []
    seen = set()
    total = 0
    allowed_roots = _BACKUP_DIRS | {"db"}
    metadata_info = None
    for info in infos:
        raw = info.filename
        if not raw or "\\" in raw or raw.startswith("/"):
            raise HTTPException(400, f"备份包含不安全路径: {raw}")
        relative = PurePosixPath(raw.rstrip("/"))
        if not relative.parts or any(part in ("", ".", "..") for part in relative.parts):
            raise HTTPException(400, f"备份包含不安全路径: {raw}")
        key = relative.as_posix().casefold()
        if key in seen:
            raise HTTPException(400, f"备份包含重复路径: {raw}")
        seen.add(key)
        if any(part == ".env" for part in relative.parts):
            raise HTTPException(400, "备份不得包含 .env")
        if info.flag_bits & 0x1:
            raise HTTPException(400, f"不支持加密文件: {raw}")
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise HTTPException(400, f"备份不得包含符号链接: {raw}")
        if len(relative.parts) == 1:
            allowed = relative.name in _BACKUP_IMPORT_TOP_FILES
        else:
            allowed = relative.parts[0] in allowed_roots
            if relative.parts[0] == "db":
                allowed = relative.as_posix() == "db/novel.db"
            elif relative.parts[0] == "cache" and len(relative.parts) > 1:
                allowed = relative.parts[1] != "failed_drafts"
        if not allowed:
            raise HTTPException(400, f"备份包含不允许的文件: {raw}")
        if info.is_dir():
            continue
        if info.file_size > MAX_BACKUP_FILE_BYTES:
            raise HTTPException(413, f"单个文件超过限制: {raw}")
        total += info.file_size
        if total > MAX_BACKUP_TOTAL_BYTES:
            raise HTTPException(413, "备份解压后总大小超过限制")
        if relative.as_posix() == BACKUP_METADATA_FILE:
            metadata_info = info
        elif relative.as_posix() != "config.py":
            members.append((info, relative))
    required = {BACKUP_METADATA_FILE, "novel_prompts.json", "bible/master_bible.md"}
    missing = required - seen
    if missing:
        raise HTTPException(400, f"备份缺少必要文件: {', '.join(sorted(missing))}")
    try:
        metadata = json.loads(zf.read(metadata_info).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, KeyError) as exc:
        raise HTTPException(400, "备份 metadata 不是有效 JSON") from exc
    return members, _validate_backup_metadata(metadata)


@app.post("/api/novels/import-backup", status_code=201)
async def api_import_backup(request: Request, id: str = Query(..., min_length=1, max_length=64)):
    try:
        novel_id = validate_slug(id)
    except NovelCreationError as exc:
        raise HTTPException(400, str(exc)) from exc
    root = NOVELS_DIR.resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / novel_id
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_BACKUP_UPLOAD_BYTES:
                raise HTTPException(413, "备份压缩包超过上传限制")
        except ValueError as exc:
            raise HTTPException(400, "Content-Length 无效") from exc
    payload = bytearray()
    async for chunk in request.stream():
        payload.extend(chunk)
        if len(payload) > MAX_BACKUP_UPLOAD_BYTES:
            raise HTTPException(413, "备份压缩包超过上传限制")
    temp_dir = Path(tempfile.mkdtemp(prefix=f".{novel_id}-restore-", dir=str(root)))
    try:
        with novel_operation(novel_id):
            if target.exists():
                raise HTTPException(409, f"小说 id 已存在: {novel_id}")
            with zipfile.ZipFile(io.BytesIO(payload)) as zf:
                members, metadata = _validated_backup_members(zf)
                for info, relative in members:
                    destination = temp_dir.joinpath(*relative.parts)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    written = 0
                    with zf.open(info) as source, destination.open("wb") as output:
                        while chunk := source.read(1024 * 1024):
                            written += len(chunk)
                            if written > MAX_BACKUP_FILE_BYTES or written > info.file_size:
                                raise HTTPException(413, f"文件解压大小异常: {info.filename}")
                            output.write(chunk)
            (temp_dir / "config.py").write_text(
                _config_py(metadata["title"], metadata["chapter_count"],
                           metadata["words_per_chapter"], metadata["volume_config"]),
                encoding="utf-8")
            restored_db = temp_dir / "db" / "novel.db"
            if restored_db.exists():
                conn = sqlite3.connect(str(restored_db))
                try:
                    result = conn.execute("PRAGMA integrity_check").fetchone()
                    if not result or result[0] != "ok":
                        raise HTTPException(400, "备份数据库完整性检查失败")
                except sqlite3.DatabaseError as exc:
                    raise HTTPException(400, "备份数据库无法打开") from exc
                finally:
                    conn.close()
            os.replace(str(temp_dir), str(target))
    except HTTPException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(400, f"无效的工作区备份: {exc}") from exc
    return {"ok": True, "id": novel_id}


@app.delete("/api/novels/{name}")
def api_delete_novel(name: str):
    try:
        validate_slug(name)
    except NovelCreationError as exc:
        raise HTTPException(404, f"小说不存在: {name}") from exc
    with novel_operation(name):
        shutil.rmtree(novel_dir(name))
    return {"ok": True, "id": name}


# ------------------------------------------------------------------ novels
@app.get("/api/novels")
def api_novels():
    out = []
    for d in sorted(NOVELS_DIR.iterdir()):
        if not d.is_dir():
            continue
        try:
            validate_slug(d.name)
        except NovelCreationError:
            continue
        title = d.name
        chapter_count = None
        pf = d / "novel_prompts.json"
        if pf.exists():
            try:
                title = json.loads(pf.read_text(encoding="utf-8")).get("_meta", {}).get("novel", d.name)
            except Exception:
                pass
        try:
            cfg = load_config(d.name)
            chapter_count = cfg.chapter_count
        except Exception:
            pass
        gen = chapter_files(d / "generated")
        words = None
        db_path = d / "db" / "novel.db"
        if db_path.is_file():
            try:
                conn = sqlite3.connect(str(db_path))
                row = conn.execute(
                    "SELECT COUNT(*), COUNT(words), COALESCE(SUM(words), 0) FROM chapter_log"
                ).fetchone()
                if row[0] == len(gen) and row[1] == row[0]:
                    words = row[2]
            except sqlite3.Error:
                pass
            finally:
                if "conn" in locals():
                    conn.close()
                    del conn
        if words is None:
            words = 0
            for fp in gen:
                try:
                    words += len(fp.read_text(encoding="utf-8"))
                except (OSError, UnicodeError):
                    continue
        out.append({"id": d.name, "title": title, "chapters_written": len(gen),
                    "chapter_count": chapter_count, "words": words})
    return out


class ThemeGenerationBody(BaseModel):
    inspiration: str = Field(default="", max_length=1000)
    genre: str = Field(default="", max_length=100)
    direction: str = Field(..., max_length=20)
    channel: str = "男频"
    protagonist_gender: str = "男主角"
    length: str = "长篇200-400章"

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, value: str) -> str:
        value = value.strip()
        if value not in THEME_DIRECTIONS:
            raise ValueError("请选择有效的主题方向")
        return value

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, value: str) -> str:
        if value not in CHANNELS:
            raise ValueError("请选择有效的频道")
        return value

    @field_validator("protagonist_gender")
    @classmethod
    def validate_protagonist_gender(cls, value: str) -> str:
        if value not in PROTAGONIST_GENDERS:
            raise ValueError("请选择有效的主角类型")
        return value

    @field_validator("length")
    @classmethod
    def validate_length(cls, value: str) -> str:
        if value not in LENGTH_PRESETS:
            raise ValueError("请选择有效的篇幅")
        return value


@app.post("/api/novel-themes/generate")
def api_generate_novel_themes(body: ThemeGenerationBody):
    try:
        options = generate_themes(
            body.inspiration, body.genre, body.direction, body.channel,
            body.protagonist_gender, body.length)
    except ThemeConfigurationError as exc:
        raise HTTPException(400, str(exc)) from exc
    except ThemeGenerationError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"options": options}


class CreateNovelBody(BaseModel):
    id: str
    title: str
    chapter_count: int = 200
    words_per_chapter: int = 3000
    genre: str = ""
    description: str = ""
    model: dict | None = None


@app.post("/api/novels", status_code=201)
def api_create_novel(body: CreateNovelBody):
    try:
        model_env = _resolve_model_env(body.model)
        with novel_operation(body.id):
            path = create_novel(body.id, body.title, body.chapter_count,
                                body.words_per_chapter, body.genre, body.description,
                                model_env=model_env)
    except FileExistsError as exc:
        raise HTTPException(409, str(exc))
    except (NovelCreationError, model_config.ModelConfigError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    return {"id": body.id, "title": body.title, "path": str(path),
            "model_configured": sorted(model_env) if model_env else []}


class ModelConfigBody(BaseModel):
    api_key: str | None = Field(default=None, max_length=10000)
    base_url: str | None = Field(default=None, max_length=2000)
    theme_model: str | None = Field(default=None, max_length=500)
    models: dict[str, str] | None = None      # {env或attr: 模型名}
    quick: dict | None = None                 # {chat_model, reasoner_model}


class OutlineBody(BaseModel):
    content: str = Field(default="", max_length=5 * 1024 * 1024)

    @field_validator("content")
    @classmethod
    def validate_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 5 * 1024 * 1024:
            raise ValueError("content 不能超过 5MB")
        return value


class ChapterContentBody(BaseModel):
    content: str = Field(default="", max_length=2 * 1024 * 1024)

    @field_validator("content")
    @classmethod
    def validate_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 2 * 1024 * 1024:
            raise ValueError("content 不能超过 2MB")
        return value


class BibleContentBody(BaseModel):
    content: str = Field(..., max_length=5 * 1024 * 1024)

    @field_validator("content")
    @classmethod
    def validate_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 5 * 1024 * 1024:
            raise ValueError("content 不能超过 5MB")
        return value


@app.get("/api/novels/{name}/model-config")
def api_model_config_get(name: str):
    novel_dir(name)
    try:
        return model_config.get_view(name)
    except Exception as exc:
        raise HTTPException(500, f"读取配置失败: {exc}")


@app.put("/api/novels/{name}/model-config")
def api_model_config_put(name: str, body: ModelConfigBody):
    novel_dir(name)
    explicit = {k: v for k, v in {
        "API_KEY": body.api_key, "API_BASE_URL": body.base_url,
        "THEME_MODEL": body.theme_model,
    }.items() if v}
    try:
        with novel_operation(name):
            updates = model_config.expand_quick(body.quick)
            if body.models:
                updates.update(model_config.sanitize_input(body.models))
            updates.update(model_config.sanitize_input(
                {k: v for k, v in explicit.items()}))
            result = model_config.save(name, updates)
    except model_config.ModelConfigError as exc:
        raise HTTPException(400, str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"保存失败: {exc}")
    return result


@app.post("/api/novels/{name}/model-config/test")
def api_model_config_test(name: str, body: dict):
    novel_dir(name)
    model = body.get("model") or model_config.read_env_file(
        model_config.env_path(novel_dir(name))).get("WRITER_MODEL") or "deepseek-chat"
    try:
        return model_config.test_connection(
            novel_dir(name), model,
            api_key=(body.get("api_key") or "").strip(),
            base_url=(body.get("base_url") or "").strip())
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


@app.get("/api/novels/{name}/status")
def api_status(name: str):
    d = novel_dir(name)
    cfg = load_config(name)
    gen = chapter_files(d / "generated")
    vols = []
    done_chs = [parse_chapter_number(f) for f in gen]
    for vk, v in cfg.volume_config.items():
        lo, hi = v["chapters"]
        done = [c for c in done_chs if lo <= c <= hi]
        vols.append({"key": vk, "name": v["name"], "lo": lo, "hi": hi,
                     "done": len(done)})
    db = NovelDB(d)
    try:
        st = db.stats()
        log_rows = [dict(r) for r in db.conn.execute(
            "SELECT * FROM chapter_log ORDER BY chapter").fetchall()]
    finally:
        db.close()

    # 待人工修订队列 + 种子数据覆盖（人物/线索/母题为空时提醒）
    queue = pending.list_pending(cfg)
    seed_counts = {"characters": 0, "clues": 0, "motifs": 0}
    seed_warnings = []
    for fname, key in (("characters.json", "characters"),
                       ("clues.json", "active_foreshadowing"),
                       ("motif_bank.json", "motifs")):
        sf = d / "bible" / fname
        try:
            data = json.loads(sf.read_text(encoding="utf-8")) if sf.exists() else {}
            items = (data or {}).get(key, {})
            count = len(items) if hasattr(items, "__len__") else 0
        except Exception:
            count, items = 0, {}
        seed_counts[key] = count
        if count == 0:
            seed_warnings.append(f"{key} 为空")

    return {"title": cfg.story_title, "chapter_count": cfg.chapter_count,
            "written": len(gen), "volumes": vols, "db": st,
            "chapter_log": log_rows,
            "pending_count": len(queue),
            "seed_coverage": {"characters": seed_counts["characters"],
                              "clues": seed_counts["clues"],
                              "motifs": seed_counts["motifs"],
                              "warnings": seed_warnings}}


# --------------------------------------------------------------- outline/titles
@app.get("/api/novels/{name}/outline", response_class=PlainTextResponse)
def api_outline(name: str):
    fp = novel_dir(name) / "bible" / "outline.md"
    return fp.read_text(encoding="utf-8") if fp.exists() else ""


@app.put("/api/novels/{name}/outline")
async def api_outline_save(name: str, body: OutlineBody):
    with novel_operation(name):
        bible_dir = novel_dir(name) / "bible"
        fp = bible_dir / "outline.md"
        _atomic_write_text(fp, body.content)
        novel_cli.mark_outline_manual(bible_dir, body.content)
    return {"ok": True, "chars": len(body.content), "manual": True}


@app.get("/api/novels/{name}/titles")
def api_titles(name: str):
    fp = novel_dir(name) / "bible" / "chapter_titles.json"
    if not fp.exists():
        return {"volumes": {}}
    return json.loads(fp.read_text(encoding="utf-8"))


class TitleBody(BaseModel):
    chapter: int = Field(..., ge=1, le=100000)
    title: str = Field(..., max_length=500)


@app.put("/api/novels/{name}/titles")
def api_title_update(name: str, body: TitleBody):
    with novel_operation(name):
        fp = novel_dir(name) / "bible" / "chapter_titles.json"
        data = json.loads(fp.read_text(encoding="utf-8"))
        for v in data.get("volumes", {}).values():
            if str(body.chapter) in v.get("chapters", {}):
                v["chapters"][str(body.chapter)] = body.title
                break
        else:
            raise HTTPException(404, "章号不在章名库")
        _atomic_write_text(fp, json.dumps(data, ensure_ascii=False, indent=2))
    return {"ok": True}


# ------------------------------------------------------------------- chapters
def _chapter_metadata(d: Path):
    titles = {}
    volumes = {}
    tf = d / "bible" / "chapter_titles.json"
    if tf.exists():
        data = json.loads(tf.read_text(encoding="utf-8"))
        for key, volume in data.get("volumes", {}).items():
            for raw, title in volume.get("chapters", {}).items():
                number = int(raw)
                titles[number] = title
                volumes[number] = {"key": key, "name": volume.get("name", key)}
    db = NovelDB(d)
    try:
        logs = {row["chapter"]: dict(row) for row in db.conn.execute(
            "SELECT chapter,status,words FROM chapter_log"
        ).fetchall()}
    finally:
        db.close()
    return titles, volumes, logs


def _chapter_item(number, fp, titles, volumes, logs, *,
                  status=None, words=None, is_pending=False):
    log = logs.get(number, {})
    if words is None:
        words = log.get("words")
    if words is None:
        words = len(fp.read_text(encoding="utf-8"))
    if status is None:
        status = log.get("status") or "generated"
    return {"num": number, "title": titles.get(number, ""), "words": words,
            "updated": fp.stat().st_mtime, "status": status,
            "volume": volumes.get(number),
            "knowledge_stale": status == "knowledge_stale",
            "pending": is_pending}


@app.get("/api/novels/{name}/chapters")
def api_chapters(name: str):
    d = novel_dir(name)
    titles, volumes, logs = _chapter_metadata(d)
    return [_chapter_item(parse_chapter_number(fp), fp, titles, volumes, logs)
            for fp in chapter_files(d / "generated")]


@app.get("/api/novels/{name}/chapters-page")
def api_chapters_page(
    name: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    q: str = Query("", max_length=100),
    status: str = Query("", max_length=40),
    chapter_from: int | None = Query(None, ge=1),
    chapter_to: int | None = Query(None, ge=1),
):
    if chapter_from is not None and chapter_to is not None and chapter_from > chapter_to:
        raise HTTPException(422, "chapter_from 不能大于 chapter_to")
    d = novel_dir(name)
    cfg = load_config(name)
    titles, volumes, logs = _chapter_metadata(d)
    needle = q.strip().casefold()
    # (number, fp, status, words, is_pending, title) 合并 generated + 待修订队列；
    # 同章待修订稿覆盖旧发布稿（去重），丢弃后旧稿重新可见。
    rows: dict[int, tuple] = {}
    for item in pending.list_pending(cfg):
        number = item["num"]
        rows[number] = (number, pending.pending_path(cfg, number), "pending",
                        item.get("words"), True, item.get("title") or "")
    for fp in chapter_files(d / "generated"):
        number = parse_chapter_number(fp)
        if number in rows:
            continue  # 待修订稿已覆盖旧发布稿
        rows[number] = (number, fp, logs.get(number, {}).get("status") or "generated",
                        None, False, titles.get(number, ""))
    matched = []
    for number in sorted(rows):
        _, fp, chapter_status, ch_words, is_pending, title = rows[number]
        if chapter_from is not None and number < chapter_from:
            continue
        if chapter_to is not None and number > chapter_to:
            continue
        if status == "pending":
            if not is_pending:
                continue
        elif status and chapter_status != status:
            continue
        if needle and needle not in str(number) and needle not in title.casefold():
            continue
        matched.append((number, fp, chapter_status, ch_words, is_pending))
    matched.sort(key=lambda row: row[0])
    page = matched[offset:offset + limit]
    items = []
    for number, fp, chapter_status, ch_words, is_pending in page:
        items.append(_chapter_item(number, fp, titles, volumes, logs,
                                   status=chapter_status, words=ch_words,
                                   is_pending=is_pending))
    return {"items": items, "total": len(matched)}


@app.get("/api/novels/{name}/chapters/{num}")
def api_chapter(name: str, num: int):
    if num <= 0:
        raise HTTPException(400, "章号必须为正数")
    fp = novel_dir(name) / "generated" / f"chapter_{num:02d}.md"
    if not fp.exists():
        raise HTTPException(404, f"第{num}章未生成")
    return {"num": num, "content": fp.read_text(encoding="utf-8")}


@app.put("/api/novels/{name}/chapters/{num}")
async def api_chapter_save(name: str, num: int, body: ChapterContentBody):
    if num <= 0:
        raise HTTPException(400, "章号必须为正数")
    with novel_operation(name):
        d = novel_dir(name)
        if num > load_config(name).chapter_count:
            raise HTTPException(422, "章号超过小说总章数")
        fp = d / "generated" / f"chapter_{num:02d}.md"
        if not fp.is_file():
            raise HTTPException(404, f"第{num}章未生成")
        content = body.content
        if not content.strip():
            raise HTTPException(422, "正文不能为空")
        from engine.knowledge import transaction
        # Retain a recoverable snapshot before invalidating published knowledge.
        with transaction(d):
            _atomic_write_text(fp, content)
            stale = NovelDB(d)
            try:
                stale.invalidate_from(num)
            finally:
                stale.close()
        r = scanner.scan(content)
        db = NovelDB(d)
        try:
            rows = r.to_rows(num)
            db.delete_style_hits(num)
            db.add_style_hits(rows)
            db.invalidate_from(num)
            db.log_chapter(num, words=len(content), status="knowledge_stale",
                           violations=sum(x[3] for x in rows
                                          if x[1] in ("禁用词", "句式", "排版")))
        finally:
            db.close()
        for cache_file in (d / "cache").glob("keeper_cache_*.json"):
            try:
                cached_chapter = int(cache_file.stem.rsplit("_", 1)[-1])
            except ValueError:
                continue
            if cached_chapter >= num:
                cache_file.unlink()
    return {"ok": True, "words": len(content), "knowledge_stale": True,
            "scan": {"passed": r.passed,
                     "violations": r.violations, "warnings": r.warnings}}


@app.get("/api/novels/{name}/scan/{num}")
def api_scan(name: str, num: int):
    fp = novel_dir(name) / "generated" / f"chapter_{num:02d}.md"
    if not fp.exists():
        raise HTTPException(404, f"第{num}章未生成")
    r = scanner.scan(fp.read_text(encoding="utf-8"))
    return {"passed": r.passed, "metrics": r.metrics,
            "violations": r.violations, "warnings": r.warnings}


class ScanPreviewBody(BaseModel):
    text: str = Field(default="", max_length=2 * 1024 * 1024)


@app.post("/api/scan-preview")
async def api_scan_preview(body: ScanPreviewBody):
    r = scanner.scan(body.text)
    return {"passed": r.passed, "metrics": r.metrics,
            "violations": r.violations, "warnings": r.warnings}


# --------------------------------------------------------------- pending 待人工修订
@app.get("/api/novels/{name}/pending")
def api_pending_list(name: str):
    return pending.list_pending(load_config(name))


@app.get("/api/novels/{name}/pending/{num}")
def api_pending_get(name: str, num: int):
    if num <= 0:
        raise HTTPException(400, "章号必须为正数")
    entry = pending.load_pending(load_config(name), num)
    if entry is None:
        raise HTTPException(404, f"第{num}章不在待修订队列")
    return {"num": num, "content": entry["content"],
            "diagnostics": entry["diagnostics"] or {}}


class PendingContentBody(BaseModel):
    content: str = Field(default="", max_length=2 * 1024 * 1024)


@app.put("/api/novels/{name}/pending/{num}")
async def api_pending_save(name: str, num: int, body: PendingContentBody):
    if num <= 0:
        raise HTTPException(400, "章号必须为正数")
    with novel_operation(name):
        cfg = load_config(name)
        entry = pending.load_pending(cfg, num)
        if entry is None:
            raise HTTPException(404, f"第{num}章不在待修订队列")
        content = body.content
        r = scanner.scan(content)
        diag = dict(entry["diagnostics"] or {})
        diag.pop("keeper_cache", None)
        diag["edited_after_review"] = content != entry["content"] or diag.get("edited_after_review", False)
        diag["words"] = len(content)
        diag["reasons"] = dict(diag.get("reasons") or {})
        diag["reasons"]["final_scan"] = [
            {"category": item.get("category", ""), "pattern": item.get("pattern", ""),
             "count": item.get("count", 0), "where": item.get("where", ""),
             "hint": item.get("hint", "")}
            for item in r.violations + r.warnings
        ]
        diag["scan_metrics"] = r.metrics
        diag["style_hits"] = r.to_rows(num)
        pending.save_pending(cfg, num, content, diag)
        return {"ok": True, "words": len(content),
                "scan": {"passed": r.passed, "violations": r.violations,
                         "warnings": r.warnings}}


@app.delete("/api/novels/{name}/pending/{num}")
async def api_pending_delete(name: str, num: int):
    if num <= 0:
        raise HTTPException(400, "章号必须为正数")
    with novel_operation(name):
        if not pending.remove_pending(load_config(name), num):
            raise HTTPException(404, f"第{num}章不在待修订队列")
        return {"ok": True}


# --------------------------------------------------------------------- bible
BIBLE_FILES = ["characters.json", "clues.json", "motif_bank.json",
               "master_bible.md", "lessons_learned.jsonl", "chapter_titles.json"]


@app.get("/api/novels/{name}/bible")
def api_bible(name: str):
    b = novel_dir(name) / "bible"
    out = {}
    for fn in BIBLE_FILES:
        fp = b / fn
        out[fn] = fp.stat().st_size if fp.exists() else 0
    return out


@app.get("/api/novels/{name}/bible/{fn}")
def api_bible_file(name: str, fn: str):
    if fn not in BIBLE_FILES + ["outline.md"]:
        raise HTTPException(400, "不允许的文件")
    fp = novel_dir(name) / "bible" / fn
    if not fp.exists():
        raise HTTPException(404)
    return PlainTextResponse(fp.read_text(encoding="utf-8"))


def _validate_bible_content(fn: str, content: str):
    try:
        if fn.endswith(".json"):
            data = json.loads(content)
            if not isinstance(data, dict):
                raise ValueError("JSON 根节点必须是对象")
            containers = {
                "characters.json": (("characters", dict),),
                "clues.json": (("clues", dict), ("active_foreshadowing", dict)),
                "motif_bank.json": (("motifs", list),),
                "chapter_titles.json": (("volumes", dict),),
            }.get(fn, ())
            for key, expected in containers:
                if key not in data or not isinstance(data[key], expected):
                    raise ValueError(f"{key} 必须是{expected.__name__}")
            values = []
            if fn == "characters.json":
                values = data["characters"].values()
            elif fn == "clues.json":
                values = [*data["clues"].values(), *data["active_foreshadowing"].values()]
            elif fn == "motif_bank.json":
                values = data["motifs"]
            elif fn == "chapter_titles.json":
                values = data["volumes"].values()
                if any(not isinstance(volume, dict)
                       or not isinstance(volume.get("chapters"), dict) for volume in values):
                    raise ValueError("volumes 中每一卷及 chapters 必须是对象")
                values = []
            if any(not isinstance(value, dict) for value in values):
                raise ValueError("关键容器中的条目必须是对象")
        elif fn.endswith(".jsonl"):
            for line_no, line in enumerate(content.splitlines(), 1):
                if line.strip() and not isinstance(json.loads(line), dict):
                    raise ValueError(f"JSONL 第 {line_no} 行必须是对象")
    except json.JSONDecodeError as exc:
        detail = f"JSON 格式错误: {exc.msg}（第 {exc.lineno} 行，第 {exc.colno} 列）"
        if fn.endswith(".jsonl"):
            detail = f"JSONL 第 {line_no} 行格式错误: {exc.msg}"
        raise HTTPException(422, detail) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def _validate_bible_import(d: Path, fn: str, content: str):
    with tempfile.TemporaryDirectory() as temp_name:
        validation_dir = Path(temp_name)
        shutil.copytree(d / "bible", validation_dir / "bible")
        (validation_dir / "generated").mkdir()
        (validation_dir / "bible" / fn).write_text(content, encoding="utf-8")
        db = NovelDB(validation_dir, auto_import=False)
        try:
            db.ensure_imported(force=True)
        finally:
            db.close()


@app.put("/api/novels/{name}/bible/{fn}")
async def api_bible_save(name: str, fn: str, body: BibleContentBody):
    if fn not in BIBLE_FILES:
        raise HTTPException(400, "不允许的文件")
    _validate_bible_content(fn, body.content)
    with novel_operation(name):
        d = novel_dir(name)
        try:
            _validate_bible_import(d, fn, body.content)
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
            raise HTTPException(422, f"Bible 数据无法导入: {exc}") from exc
        from engine.knowledge import transaction
        from engine.authoring import record_edit, apply_edits
        with transaction(d):
            fp = d / "bible" / fn
            previous = fp.read_text(encoding="utf-8") if fp.exists() else "{}"
            _atomic_write_text(fp, body.content)
            db = NovelDB(d, auto_import=False)
            try:
                synced = db.ensure_imported(force=True)
            except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
                raise HTTPException(422, f"Bible 数据无法导入: {exc}") from exc
            finally:
                db.close()
            if fn in ("characters.json", "clues.json"):
                record_edit(d, fn, json.loads(previous), json.loads(body.content))
                last = max((parse_chapter_number(p) for p in chapter_files(d / "generated")), default=0)
                apply_edits(d, last)
    return {"ok": True, "synced": synced}


class CharacterBody(BaseModel):
    profile: dict | None = None
    chapter: int | None = Field(default=None, ge=1)


class ClueBody(BaseModel):
    name: str | None = None
    type: str | None = None
    description: str | None = None
    introduced_chapter: int | None = Field(default=None, ge=1)
    intended_reveal_chapter: int | None = Field(default=None, ge=1)
    intended_resolution_chapter: int | None = Field(default=None, ge=1)
    resolved: bool | None = None
    state: dict | None = None
    chapter: int | None = Field(default=None, ge=1)


class ForeshadowBody(BaseModel):
    name: str | None = None
    status: str | None = Field(
        default=None, pattern="^(pending|active|escalated|resolved|retired)$"
    )
    introduced_chapter: int | None = Field(default=None, ge=1)
    intended_payoff_chapter: int | None = Field(default=None, ge=1)
    payoff_start_chapter: int | None = Field(default=None, ge=1)
    payoff_end_chapter: int | None = Field(default=None, ge=1)
    resolved_chapter: int | None = Field(default=None, ge=1)
    description: str | None = None
    hinted_chapters: list[int] | None = None
    scope: str | None = None
    importance: str | None = None
    touch_interval: int | None = Field(default=None, ge=1)


# ------------------------------------------------------------------ db browse
@app.post("/api/novels/{name}/knowledge-base/sync")
def api_knowledge_base_sync(name: str):
    with novel_operation(name):
        db = NovelDB(novel_dir(name), auto_import=False)
        try:
            counts = db.ensure_imported(force=True)
            stats = db.stats()
        finally:
            db.close()
    return {"ok": True, "counts": counts, "stats": stats}


def _foreshadow_response(row) -> dict:
    value = dict(row)
    return {
        "id": value["id"],
        "name": value["name"],
        "status": value["status"],
        "introduced_chapter": value["planted_ch"],
        "intended_payoff_chapter": value["payoff_ch"],
        "payoff_start_chapter": value.get("payoff_start_ch"),
        "payoff_end_chapter": value.get("payoff_end_ch"),
        "resolved_chapter": value["resolved_ch"],
        "description": value["description"],
        "scope": value.get("scope"),
        "importance": value.get("importance"),
        "touch_interval": value.get("touch_interval"),
        "hinted_chapters": json.loads(value["hinted_chs"] or "[]"),
        **({"days_dark": value["days_dark"]} if "days_dark" in value else {}),
    }


def _patch_db_and_bible(d: Path, kind: str, item_id: str, changes: dict):
    from engine.authoring import record_edit, apply_edits
    from engine.knowledge import transaction
    filename = "characters.json" if kind == "character" else "clues.json"
    with transaction(d):
        before = json.loads((d / "bible" / filename).read_text(encoding="utf-8"))
        chapter = changes.get("chapter")
        _apply_db_and_bible_patch(d, kind, item_id, changes)
        after = json.loads((d / "bible" / filename).read_text(encoding="utf-8"))
        record_edit(d, filename, before, after, chapter)
        at = chapter if chapter is not None else max(
            (parse_chapter_number(p) for p in chapter_files(d / "generated")), default=0)
        apply_edits(d, at)


def _apply_db_and_bible_patch(d: Path, kind: str, item_id: str, changes: dict):
    db = NovelDB(d)
    bible_file = d / "bible" / ("characters.json" if kind == "character" else "clues.json")
    original = bible_file.read_text(encoding="utf-8")
    bible = json.loads(original)
    try:
        if kind == "character":
            row = db.conn.execute(
                "SELECT * FROM characters WHERE name=?", (item_id,),
            ).fetchone()
            current = json.loads(row["profile_json"] or "{}") if row else {}
            profile_patch = changes.get("profile")
            if profile_patch is not None:
                current.update(profile_patch)
            chapter = changes.get("chapter") if "chapter" in changes else None
            bible.setdefault("characters", {})[item_id] = current
            db.conn.execute("BEGIN IMMEDIATE")
            db.upsert_character(item_id, current, chapter, commit=False)
        elif kind == "clue":
            row = db.conn.execute("SELECT * FROM clues WHERE id=?", (item_id,)).fetchone()
            current = ({
                "name": row["name"], "type": row["type"],
                "description": row["description"],
                "introduced_chapter": row["introduced_ch"],
                "intended_reveal_chapter": row["intended_reveal_ch"],
                "resolved": bool(row["resolved"]),
                "state": json.loads(row["state_json"] or "{}"),
            } if row else {"name": "", "type": "", "description": "",
                           "resolved": False, "state": {}})
            state_patch = changes.pop("state", None)
            chapter = changes.pop("chapter", None)
            current.update(changes)
            if state_patch is not None:
                current.setdefault("state", {}).update(state_patch)
            bible.setdefault("clues", {})[item_id] = {
                key: value for key, value in current.items() if key != "state"
            } | current.get("state", {})
            db.conn.execute("BEGIN IMMEDIATE")
            db.upsert_clue(item_id, current, chapter, commit=False)
        else:
            row = db.conn.execute(
                "SELECT * FROM foreshadowing WHERE id=?", (item_id,),
            ).fetchone()
            current = (_foreshadow_response(row) if row else {
                "name": "", "status": "pending", "description": "",
                "hinted_chapters": [],
            })
            current.pop("id", None)
            current.update(changes)
            bible.setdefault("active_foreshadowing", {})[item_id] = current
            db.conn.execute("BEGIN IMMEDIATE")
            db.upsert_foreshadow(item_id, current, commit=False)
        _atomic_write_text(
            bible_file, json.dumps(bible, ensure_ascii=False, indent=2),
        )
        signature = db._bible_signature()
        db.conn.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES('bible_signature',?)",
            (signature,),
        )
        db.conn.commit()
    except Exception:
        db.conn.rollback()
        _atomic_write_text(bible_file, original)
        raise
    finally:
        db.close()


@app.get("/api/novels/{name}/db/foreshadowing")
def api_db_foreshadow(name: str, current: int = 1):
    db = NovelDB(novel_dir(name))
    try:
        buckets = db.open_foreshadowing(current)
        rows = db.conn.execute("SELECT * FROM foreshadowing").fetchall()
    finally:
        db.close()
    return {
        "rows": [_foreshadow_response(row) for row in rows],
        "buckets": {
            key: [_foreshadow_response(item) for item in bucket]
            for key, bucket in buckets.items()
        },
    }


@app.patch("/api/novels/{name}/db/foreshadowing/{fid}")
def api_db_foreshadow_update(name: str, fid: str, body: ForeshadowBody):
    with novel_operation(name):
        _patch_db_and_bible(
            novel_dir(name), "foreshadow", fid,
            body.model_dump(exclude_unset=True),
        )
    return {"ok": True, "id": fid}


@app.get("/api/novels/{name}/db/facts")
def api_db_facts(
    name: str,
    q: str = Query("", max_length=500),
    chapter: int = Query(0, ge=0, le=100000),
    limit: int = Query(30, ge=1, le=200),
):
    db = NovelDB(novel_dir(name))
    try:
        if q:
            rows = db.search_facts(q.split(), before_ch=chapter or 10 ** 9, limit=limit)
        else:
            rows = db.conn.execute(
                "SELECT * FROM chapter_facts WHERE chapter<? ORDER BY id DESC LIMIT ?",
                (chapter or 10 ** 9, limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


@app.get("/api/novels/{name}/db/characters")
def api_db_characters(name: str):
    db = NovelDB(novel_dir(name))
    try:
        rows = db.conn.execute("SELECT * FROM characters").fetchall()
        chars = []
        for row in rows:
            char = dict(row)
            states = db.conn.execute(
                "SELECT chapter, state_json FROM character_states WHERE character=? "
                "ORDER BY chapter DESC LIMIT 3", (char["name"],)).fetchall()
            chars.append({
                "name": char["name"],
                "role": char["role"],
                "voice_print": char["voice_print"],
                "first_appearance_chapter": char["first_chapter"],
                "updated_chapter": char["updated_chapter"],
                "profile": json.loads(char["profile_json"] or "{}"),
                "recent_states": [
                    {"chapter": state["chapter"],
                     "state": json.loads(state["state_json"] or "{}")}
                    for state in states
                ],
            })
        return chars
    finally:
        db.close()


@app.patch("/api/novels/{name}/db/characters/{character}")
def api_db_character_update(name: str, character: str, body: CharacterBody):
    with novel_operation(name):
        _patch_db_and_bible(
            novel_dir(name), "character", character,
            body.model_dump(exclude_unset=True),
        )
    return {"ok": True, "name": character}


@app.get("/api/novels/{name}/db/clues")
def api_db_clues(name: str):
    db = NovelDB(novel_dir(name))
    try:
        rows = db.conn.execute("SELECT * FROM clues ORDER BY id").fetchall()
    finally:
        db.close()
    return [{
        "id": row["id"],
        "name": row["name"],
        "type": row["type"],
        "description": row["description"],
        "introduced_chapter": row["introduced_ch"],
        "intended_reveal_chapter": row["intended_reveal_ch"],
        "resolved": bool(row["resolved"]),
        "state": json.loads(row["state_json"] or "{}"),
        "updated_chapter": row["updated_ch"],
    } for row in rows]


@app.patch("/api/novels/{name}/db/clues/{cid}")
def api_db_clue_update(name: str, cid: str, body: ClueBody):
    with novel_operation(name):
        _patch_db_and_bible(
            novel_dir(name), "clue", cid,
            body.model_dump(exclude_unset=True),
        )
    return {"ok": True, "id": cid}


@app.get("/api/novels/{name}/db/motifs")
def api_db_motifs(name: str):
    db = NovelDB(novel_dir(name))
    try:
        rows = [dict(r) for r in db.conn.execute("SELECT * FROM motifs ORDER BY id").fetchall()]
    finally:
        db.close()
    return [{
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "used_in_chapters": json.loads(row["used_chs"] or "[]"),
    } for row in rows]


@app.get("/api/novels/{name}/db/style-hits")
def api_db_style_hits(name: str):
    db = NovelDB(novel_dir(name))
    try:
        rows = db.conn.execute(
            "SELECT category, pattern, SUM(count) total, COUNT(*) chapters FROM style_hits "
            "GROUP BY category, pattern ORDER BY total DESC LIMIT 50").fetchall()
        by_ch = db.conn.execute(
            "SELECT chapter, COUNT(*) hits FROM style_hits GROUP BY chapter ORDER BY chapter").fetchall()
        return {"patterns": [dict(r) for r in rows], "by_chapter": [dict(r) for r in by_ch]}
    finally:
        db.close()


@app.get("/api/novels/{name}/db/lessons")
def api_db_lessons(name: str):
    db = NovelDB(novel_dir(name))
    try:
        return [dict(r) for r in db.lessons_recent(50)]
    finally:
        db.close()


# ---------------------------------------------------------------- style kit
SK = ROOT / "engine" / "style_kit"


@app.get("/api/style-kit")
def api_style_kit():
    return json.loads((SK / "banned_words.json").read_text(encoding="utf-8"))


@app.put("/api/style-kit")
async def api_style_kit_save(body: dict):
    if "hard_words" not in body or not isinstance(body["hard_words"], list):
        raise HTTPException(400, "结构需含 hard_words 列表")
    (SK / "banned_words.json").write_text(
        json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    scanner.RULES_FILE = SK / "banned_words.json"
    return {"ok": True, "hard_words": len(body["hard_words"])}


@app.get("/api/style-kit/docs/{doc}")
def api_style_doc(doc: str):
    fp = SK / f"{doc}.md"
    if doc not in ("techniques", "tomato_rules") or not fp.exists():
        raise HTTPException(404)
    return PlainTextResponse(fp.read_text(encoding="utf-8"))


# ----------------------------------------------------------------- pipeline
def _volume_of(cfg, chapter: int):
    for vk, v in cfg.volume_config.items():
        lo, hi = v["chapters"]
        if lo <= chapter <= hi:
            return vk, dict(v, key=vk)
    last_key = list(cfg.volume_config)[-1]
    return last_key, dict(cfg.volume_config[last_key], key=last_key)


@app.get("/api/novels/{name}/pipeline")
def api_pipeline(name: str):
    """返回生产流水线状态：每个环节的完成判定 + 建议的下一步。"""
    d = novel_dir(name)
    cfg = load_config(name)
    b = d / "bible"
    gen = d / "generated"

    written = [parse_chapter_number(fp) for fp in chapter_files(gen)]
    missing = [c for c in range(1, (written[-1] + 1) if written else 1) if c not in written]

    readiness = novel_cli.planning_readiness(cfg)
    outline_fp = b / "outline.md"
    outline_text = outline_fp.read_text(encoding="utf-8") if outline_fp.exists() else ""
    outline_chapters = len(readiness["outline_numbers"])
    outline_ready = readiness["outline_ready"]
    titles_total = len(readiness["titles"])
    titles_auto = len(readiness["placeholders"])
    titles_ready = readiness["titles_ready"]

    next_chapter = (written[-1] + 1) if written else 1
    while next_chapter <= cfg.chapter_count and next_chapter in written:
        next_chapter += 1
    gaps = [c for c in range(1, min(next_chapter, cfg.chapter_count + 1))
            if c not in written]
    if gaps:
        next_chapter = gaps[0]
    missing = gaps
    vol_key, vol = _volume_of(cfg, min(next_chapter, cfg.chapter_count))
    lo, hi = vol["chapters"]

    # 待总结的卷 = 章节全部写完 但 summary 文件不存在
    pending_summaries = []
    for vk, v in cfg.volume_config.items():
        vlo, vhi = v["chapters"]
        vdone = len([c for c in written if vlo <= c <= vhi])
        vnum = vk.rsplit("_", 1)[-1]
        has_summary = (gen / f"volume_{vnum}_summary.md").exists()
        if vdone >= (vhi - vlo + 1) and vdone > 0 and not has_summary:
            pending_summaries.append({"key": vk, "num": int(vnum), "name": v["name"]})
    vol_done = len([c for c in written if lo <= c <= hi])

    from engine.knowledge import stale_chapters
    stale = stale_chapters(cfg)
    pending_count = len(pending.list_pending(cfg))
    interrupted = (d / "knowledge_transaction.json").exists()
    if interrupted:
        stage = "recover"
    elif stale:
        stage = "rebuild"
    elif pending_count:
        stage = "revision"
    elif not outline_ready:
        stage = "outline"
    elif not titles_ready:
        stage = "titles"
    elif missing:
        stage = "fill_gaps"
    elif pending_summaries:
        stage = "volume_summary"
    elif next_chapter > cfg.chapter_count:
        stage = "publish"
    else:
        stage = "write"

    target_summary = pending_summaries[0] if pending_summaries else None
    steps = [
        {"key": "outline", "title": "① 生成全书大纲", "file": "bible/outline.md",
         "done": outline_ready, "detected": outline_chapters,
         "missing": readiness["missing_outline"][:20],
         "unit": "章条目", "available": True},
        {"key": "titles", "title": "② 提取章名库", "file": "bible/chapter_titles.json",
         "done": titles_ready, "detected": titles_total, "auto_named": titles_auto,
         "missing": readiness["missing_titles"][:20],
         "unit": "章名", "available": outline_ready},
        {"key": "write", "title": f"③ 逐章写作 · {vol['name']}", "file": "generated/",
         "done": next_chapter > cfg.chapter_count, "detected": len(written),
         "unit": f"/ {cfg.chapter_count} 章", "available": outline_ready and titles_ready and not stale and not pending_count and not interrupted,
         "detail": {"volume": vol["name"], "range": [lo, hi], "volume_done": vol_done,
                    "volume_total": hi - lo + 1, "next_chapter": next_chapter,
                    "missing": missing[:20]}},
        {"key": "summary",
         "title": f"④ 卷末总结 · {target_summary['name'] if target_summary else '按卷收尾'}",
         "file": (f"generated/volume_{target_summary['num']}_summary.md"
                  if target_summary else "generated/volume_N_summary.md"),
         "done": not pending_summaries and bool(written),
         "pending": pending_summaries, "unit": "",
         "available": bool(pending_summaries)},
        {"key": "publish", "title": "⑤ 发布与宣传", "file": "",
         "done": next_chapter > cfg.chapter_count and not pending_summaries, "unit": "",
         "available": True},
    ]
    return {"stage": stage, "steps": steps, "next_chapter": next_chapter,
            "written": written[-1] if written else 0, "written_count": len(written),
            "chapter_count": cfg.chapter_count, "current_volume": vol_key,
            "pending_count": pending_count, "stale_chapters": stale,
            "interrupted_archive": interrupted}


# -------------------------------------------------------------------- tasks
class TaskBody(BaseModel):
    chapter: int | None = Field(default=None, ge=1, le=100000)
    chapter_end: int | None = Field(default=None, ge=1, le=100000)
    volume: int | None = Field(default=None, ge=1, le=100000)
    prompt: str = Field(default="", max_length=10000)
    overwrite: bool = False
    force: bool = False
    outline_override: bool = False


ALLOWED = {"outline", "titles", "generate", "revise", "summary", "db", "publish", "rebuild", "recover", "prepare"}


@app.get("/api/novels/{name}/tasks")
def api_task_list(name: str):
    return T.list_tasks(name)


@app.post("/api/novels/{name}/tasks/{action}")
async def api_task(name: str, action: str, body: TaskBody):
    d = novel_dir(name)
    if action not in ALLOWED:
        raise HTTPException(400, f"不支持: {action}")
    args: list[str] = []
    steps = None
    if action == "generate":
        if body.chapter is None or body.chapter <= 0:
            raise HTTPException(400, "chapter 必须为正数")
        cfg = load_config(name)
        start = body.chapter
        end = body.chapter_end or start
        if end < start:
            raise HTTPException(400, "chapter_end 不能小于 chapter")
        if end > cfg.chapter_count:
            raise HTTPException(400, f"超出本章总数 {cfg.chapter_count}")
        if end - start + 1 > 20:
            raise HTTPException(422, "单次批量最多连续 20 章，成本高且便于中断")
        readiness = novel_cli.planning_readiness(cfg)
        if not body.outline_override and not readiness["outline_ready"]:
            raise HTTPException(409, "写作门禁：全书大纲未按章号完整覆盖")
        if not body.outline_override and not readiness["titles_ready"]:
            raise HTTPException(409, "写作门禁：章名未完整生成或仍含占位名")
        from engine.knowledge import check_ready
        try:
            check_ready(cfg, start)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        suffix = (["-p", body.prompt] if body.prompt else [])
        if body.overwrite:
            suffix += ["--overwrite"]
        if body.outline_override:
            suffix += ["--outline-override"]
        if end > start:
            steps = [{"action": "generate", "args": [str(n)] + suffix}
                     for n in range(start, end + 1)]
        args = [str(start)] + suffix
    elif action == "revise":
        if body.chapter is None or body.chapter <= 0 or not body.prompt:
            raise HTTPException(400, "chapter 必须为正数且 prompt 不能为空")
        if not (d / "generated" / f"chapter_{body.chapter:02d}.md").exists():
            raise HTTPException(404, f"第 {body.chapter} 章尚未生成，无法修订")
        args = [str(body.chapter), body.prompt]
    elif action == "summary":
        if body.volume is None or body.volume <= 0:
            raise HTTPException(400, "volume 必须为正数")
        cfg = load_config(name)
        volume = cfg.volume_config.get(f"volume_{body.volume}")
        if not volume:
            raise HTTPException(404, f"未找到第 {body.volume} 卷")
        lo, hi = volume["chapters"]
        if not chapter_files(d / "generated", first_chapter=lo, last_chapter=hi):
            raise HTTPException(409, f"第{body.volume}卷尚未生成任何章节")
        args = [str(body.volume)] + (["-p", body.prompt] if body.prompt else [])
    elif action == "outline":
        manifest = d / "bible" / "outline_manifest.json"
        if manifest.exists() and not body.force:
            try:
                if json.loads(manifest.read_text(encoding="utf-8")).get("outline", {}).get("status") == "manual":
                    raise HTTPException(409, "outline.md 已人工修改；普通继续不会覆盖，请使用重新生成（force）")
            except (OSError, ValueError, TypeError):
                pass
        args = (["-p", body.prompt] if body.prompt else []) + (["--force"] if body.force else [])
    elif action == "titles":
        if not (d / "bible" / "outline.md").exists():
            raise HTTPException(409, "缺少 outline.md，无法提取章名")
        args = ["-p", body.prompt] if body.prompt else []
    elif action == "publish":
        if body.chapter is None or body.chapter <= 0:
            raise HTTPException(400, "chapter 必须为正数")
        if not (d / "revision" / f"chapter_{body.chapter:02d}.md").exists():
            raise HTTPException(404, f"第 {body.chapter} 章不在待修订队列")
        args = [str(body.chapter)]
    elif action == "db":
        args = ["init"]
    try:
        tid = T.submit(name, action, args) if steps is None else T.submit(name, action, args, steps=steps)
    except T.BusyError as e:
        raise HTTPException(409, str(e))
    return {"task_id": tid, "steps": len(steps or [1])}


@app.post("/api/tasks/{tid}/cancel")
def api_task_cancel(tid: str):
    result = T.cancel(tid)
    if result is None:
        raise HTTPException(404, "任务不存在")
    return result


@app.get("/api/tasks/{tid}/events")
async def api_task_events(tid: str):
    if not T.get(tid):
        raise HTTPException(404)
    async def gen():
        async for line in T.events(tid):
            yield f"data: {json.dumps(line, ensure_ascii=False)}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")
