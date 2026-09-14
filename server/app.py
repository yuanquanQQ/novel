"""小说创作引擎 — Web 控制台后端 (FastAPI)"""
import json
import re
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.settings import NOVELS_DIR, load_config  # noqa: E402
from engine.db import NovelDB  # noqa: E402
from engine.style_kit import scanner  # noqa: E402
from server import tasks as T  # noqa: E402

app = FastAPI(title="Novel Console API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"], allow_headers=["*"])


def novel_dir(name: str) -> Path:
    root = NOVELS_DIR.resolve()
    if ".." in Path(name).parts:
        raise HTTPException(404, f"小说不存在: {name}")
    d = (root / name).resolve()
    if d.parent != root or not d.is_dir():
        raise HTTPException(404, f"小说不存在: {name}")
    return d


# ------------------------------------------------------------------ novels
@app.get("/api/novels")
def api_novels():
    out = []
    for d in sorted(NOVELS_DIR.iterdir()):
        if not d.is_dir():
            continue
        title = d.name
        chapter_count = None
        pf = d / "novel_prompts.json"
        if pf.exists():
            try:
                title = json.loads(pf.read_text(encoding="utf-8")).get("_meta", {}).get("novel", d.name)
            except Exception:
                pass
        cf = d / "config.py"
        try:
            cfg = load_config(d.name)
            chapter_count = cfg.chapter_count
        except Exception:
            pass
        gen = list((d / "generated").glob("chapter_*.md")) if (d / "generated").exists() else []
        words = 0
        try:
            for f in gen:
                words += len(f.read_text(encoding="utf-8"))
        except Exception:
            pass
        out.append({"id": d.name, "title": title, "chapters_written": len(gen),
                    "chapter_count": chapter_count, "words": words})
    return out


@app.get("/api/novels/{name}/status")
def api_status(name: str):
    d = novel_dir(name)
    cfg = load_config(name)
    gen = sorted((d / "generated").glob("chapter_*.md"))
    vols = []
    done_chs = []
    for f in gen:
        try:
            done_chs.append(int(f.stem.split("_")[1]))
        except (IndexError, ValueError):
            pass
    for vk, v in cfg.volume_config.items():
        lo, hi = v["chapters"]
        done = [c for c in done_chs if lo <= c <= hi]
        vols.append({"key": vk, "name": v["name"], "lo": lo, "hi": hi,
                     "done": len(done)})
    db = NovelDB(d)
    st = db.stats()
    log_rows = [dict(r) for r in db.conn.execute(
        "SELECT * FROM chapter_log ORDER BY chapter").fetchall()]
    db.close()
    return {"title": cfg.story_title, "chapter_count": cfg.chapter_count,
            "written": len(gen), "volumes": vols, "db": st,
            "chapter_log": log_rows}


# --------------------------------------------------------------- outline/titles
@app.get("/api/novels/{name}/outline", response_class=PlainTextResponse)
def api_outline(name: str):
    fp = novel_dir(name) / "bible" / "outline.md"
    return fp.read_text(encoding="utf-8") if fp.exists() else ""


@app.put("/api/novels/{name}/outline")
async def api_outline_save(name: str, body: dict):
    fp = novel_dir(name) / "bible" / "outline.md"
    fp.write_text(body.get("content", ""), encoding="utf-8")
    return {"ok": True, "chars": len(body.get("content", ""))}


@app.get("/api/novels/{name}/titles")
def api_titles(name: str):
    fp = novel_dir(name) / "bible" / "chapter_titles.json"
    if not fp.exists():
        return {"volumes": {}}
    return json.loads(fp.read_text(encoding="utf-8"))


class TitleBody(BaseModel):
    chapter: int
    title: str


@app.put("/api/novels/{name}/titles")
def api_title_update(name: str, body: TitleBody):
    fp = novel_dir(name) / "bible" / "chapter_titles.json"
    data = json.loads(fp.read_text(encoding="utf-8"))
    for v in data.get("volumes", {}).values():
        if str(body.chapter) in v.get("chapters", {}):
            v["chapters"][str(body.chapter)] = body.title
            break
    else:
        raise HTTPException(404, "章号不在章名库")
    fp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True}


# ------------------------------------------------------------------- chapters
@app.get("/api/novels/{name}/chapters")
def api_chapters(name: str):
    d = novel_dir(name)
    tf = d / "bible" / "chapter_titles.json"
    titles = {}
    if tf.exists():
        data = json.loads(tf.read_text(encoding="utf-8"))
        for v in data.get("volumes", {}).values():
            titles.update({int(k): t for k, t in v.get("chapters", {}).items()})
    out = []
    chapters = []
    for fp in (d / "generated").glob("chapter_*.md"):
        match = re.fullmatch(r"chapter_(\d+)\.md", fp.name)
        if match:
            chapters.append((int(match.group(1)), fp))
    for n, fp in sorted(chapters):
        text = fp.read_text(encoding="utf-8")
        out.append({"num": n, "title": titles.get(n, ""), "words": len(text),
                    "updated": fp.stat().st_mtime})
    return out


@app.get("/api/novels/{name}/chapters/{num}")
def api_chapter(name: str, num: int):
    if num <= 0:
        raise HTTPException(400, "章号必须为正数")
    fp = novel_dir(name) / "generated" / f"chapter_{num:02d}.md"
    if not fp.exists():
        raise HTTPException(404, f"第{num}章未生成")
    return {"num": num, "content": fp.read_text(encoding="utf-8")}


@app.put("/api/novels/{name}/chapters/{num}")
async def api_chapter_save(name: str, num: int, body: dict):
    if num <= 0:
        raise HTTPException(400, "章号必须为正数")
    fp = novel_dir(name) / "generated" / f"chapter_{num:02d}.md"
    content = body.get("content", "")
    fp.write_text(content, encoding="utf-8")
    r = scanner.scan(content)
    db = NovelDB(novel_dir(name))
    rows = r.to_rows(num)
    db.delete_style_hits(num)
    db.add_style_hits(rows)
    db.log_chapter(num, words=len(content),
                   violations=sum(x[3] for x in rows
                                  if x[1] in ("禁用词", "句式", "排版")))
    db.close()
    return {"ok": True, "words": len(content),
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


@app.post("/api/scan-preview")
async def api_scan_preview(body: dict):
    r = scanner.scan(body.get("text", ""))
    return {"passed": r.passed, "metrics": r.metrics,
            "violations": r.violations, "warnings": r.warnings}


# --------------------------------------------------------------------- bible
BIBLE_FILES = ["characters.json", "clues.json", "motif_bank.json",
               "master_bible.md", "lessons_learned.jsonl"]


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
    if fn not in BIBLE_FILES + ["outline.md", "chapter_titles.json"]:
        raise HTTPException(400, "不允许的文件")
    fp = novel_dir(name) / "bible" / fn
    if not fp.exists():
        raise HTTPException(404)
    return PlainTextResponse(fp.read_text(encoding="utf-8"))


@app.put("/api/novels/{name}/bible/{fn}")
async def api_bible_save(name: str, fn: str, body: dict):
    if fn not in BIBLE_FILES + ["chapter_titles.json"]:
        raise HTTPException(400, "不允许的文件")
    content = body.get("content", "")
    if fn.endswith(".json") or fn.endswith(".jsonl"):
        if fn.endswith(".json"):
            json.loads(content)  # 校验
    fp = novel_dir(name) / "bible" / fn
    fp.write_text(content, encoding="utf-8")
    return {"ok": True}


# ------------------------------------------------------------------ db browse
@app.get("/api/novels/{name}/db/foreshadowing")
def api_db_foreshadow(name: str, current: int = 1):
    db = NovelDB(novel_dir(name))
    buckets = db.open_foreshadowing(current)
    rows = [dict(r) for r in db.conn.execute("SELECT * FROM foreshadowing").fetchall()]
    db.close()
    for r in rows:
        r["hinted_chs"] = json.loads(r["hinted_chs"] or "[]")
    return {"rows": rows, "buckets": {k: [dict(x) for x in v] for k, v in buckets.items()}}


@app.get("/api/novels/{name}/db/facts")
def api_db_facts(name: str, q: str = "", chapter: int = 0, limit: int = 30):
    db = NovelDB(novel_dir(name))
    if q:
        rows = db.search_facts(q.split(), before_ch=chapter or 10 ** 9, limit=limit)
    else:
        rows = db.conn.execute(
            "SELECT * FROM chapter_facts WHERE chapter<? ORDER BY id DESC LIMIT ?",
            (chapter or 10 ** 9, limit)).fetchall()
    db.close()
    return [dict(r) for r in rows]


@app.get("/api/novels/{name}/db/characters")
def api_db_characters(name: str):
    db = NovelDB(novel_dir(name))
    chars = [dict(r) for r in db.conn.execute(
        "SELECT name, role, voice_print, first_chapter, updated_chapter FROM characters").fetchall()]
    for c in chars:
        states = db.conn.execute(
            "SELECT chapter, state_json FROM character_states WHERE character=? "
            "ORDER BY chapter DESC LIMIT 3", (c["name"],)).fetchall()
        c["recent_states"] = [dict(s) for s in states]
    db.close()
    return chars


@app.get("/api/novels/{name}/db/style-hits")
def api_db_style_hits(name: str):
    db = NovelDB(novel_dir(name))
    rows = db.conn.execute(
        "SELECT category, pattern, SUM(count) total, COUNT(*) chapters FROM style_hits "
        "GROUP BY category, pattern ORDER BY total DESC LIMIT 50").fetchall()
    by_ch = db.conn.execute(
        "SELECT chapter, COUNT(*) hits FROM style_hits GROUP BY chapter ORDER BY chapter").fetchall()
    db.close()
    return {"patterns": [dict(r) for r in rows], "by_chapter": [dict(r) for r in by_ch]}


@app.get("/api/novels/{name}/db/lessons")
def api_db_lessons(name: str):
    db = NovelDB(novel_dir(name))
    rows = db.lessons_recent(50)
    db.close()
    return [dict(r) for r in rows]


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


# -------------------------------------------------------------------- tasks
class TaskBody(BaseModel):
    chapter: int | None = None
    volume: int | None = None
    prompt: str = ""


ALLOWED = {"outline", "titles", "generate", "revise", "summary", "db"}


@app.get("/api/novels/{name}/tasks")
def api_task_list(name: str):
    return T.list_tasks(name)


@app.post("/api/novels/{name}/tasks/{action}")
async def api_task(name: str, action: str, body: TaskBody):
    novel_dir(name)
    if action not in ALLOWED:
        raise HTTPException(400, f"不支持: {action}")
    args: list[str] = []
    if action == "generate":
        if body.chapter is None or body.chapter <= 0:
            raise HTTPException(400, "chapter 必须为正数")
        args = [str(body.chapter)] + (["-p", body.prompt] if body.prompt else [])
    elif action == "revise":
        if body.chapter is None or body.chapter <= 0 or not body.prompt:
            raise HTTPException(400, "chapter 必须为正数且 prompt 不能为空")
        args = [str(body.chapter), body.prompt]
    elif action == "summary":
        if body.volume is None or body.volume <= 0:
            raise HTTPException(400, "volume 必须为正数")
        args = [str(body.volume)] + (["-p", body.prompt] if body.prompt else [])
    elif action == "outline":
        args = ["-p", body.prompt] if body.prompt else []
    elif action == "titles":
        args = ["-p", body.prompt] if body.prompt else []
    elif action == "db":
        args = ["init"]
    if T.running_task(name):
        raise HTTPException(409, "该小说已有任务运行中")
    try:
        tid = T.submit(name, action, args)
    except T.BusyError as e:
        raise HTTPException(409, str(e))
    return {"task_id": tid}


@app.get("/api/tasks/{tid}/events")
async def api_task_events(tid: str):
    if not T.get(tid):
        raise HTTPException(404)
    async def gen():
        async for line in T.events(tid):
            yield f"data: {json.dumps(line, ensure_ascii=False)}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")
