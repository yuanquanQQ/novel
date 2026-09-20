# 小说创作引擎 — 统一命令行入口
# ==========================================
# python novel.py --novel <name> outline              → 生成全书大纲框架 → bible/outline.md
# python novel.py --novel <name> titles               → 根据大纲生成全部章名 → bible/chapter_titles.json
# python novel.py --novel <name> titles --prompt "要求" → 带指令重新生成章名
# python novel.py --novel <name> generate <ch>        → 生成第N章
# python novel.py --novel <name> generate <ch> -p "指令" → 带创作指令
# python novel.py --novel <name> revise <ch> <修改原因> → 修订第N章
# python novel.py --novel <name> summary <卷号>       → 生成卷末总结
# python novel.py --novel <name> summary <卷号> -r "要求" → 修订卷末总结
# python novel.py --list                              → 列出所有小说
# python novel.py --novel <name> status                → 查看当前进度

import sys
import json
import hashlib
import logging
import os
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_ROOT))

from engine.chapter_files import chapter_files, parse_chapter_number
from engine.settings import set_novel, get_novel, get_novel_dir, get_config, NOVELS_DIR
from engine import pending

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("novel")


def _parse_args():
    args = sys.argv[1:]
    parsed = {
        "novel": "",
        "command": "",
        "chapter": None,
        "volume": None,
        "prompt": "",
        "content": "",
        "id": "",
        "title": "",
        "chapter_count": 200,
        "words_per_chapter": 3000,
        "genre": "",
        "description": "",
        "overwrite": False,
        "force": False,
        "outline_override": False,
    }
    i = 0
    while i < len(args):
        a = args[i]
        if a == "create":
            parsed["command"] = "create"
        elif a == "--id" and i + 1 < len(args):
            i += 1; parsed["id"] = args[i]
        elif a == "--title" and i + 1 < len(args):
            i += 1; parsed["title"] = args[i]
        elif a in ("--chapters", "--chapter-count") and i + 1 < len(args):
            i += 1; parsed["chapter_count"] = int(args[i])
        elif a in ("--words", "--words-per-chapter") and i + 1 < len(args):
            i += 1; parsed["words_per_chapter"] = int(args[i])
        elif a == "--genre" and i + 1 < len(args):
            i += 1; parsed["genre"] = args[i]
        elif a == "--description" and i + 1 < len(args):
            i += 1; parsed["description"] = args[i]
        elif a == "--novel" and i + 1 < len(args):
            i += 1; parsed["novel"] = args[i]
        elif a == "--list":
            parsed["command"] = "list"
        elif a == "--overwrite":
            parsed["overwrite"] = True
        elif a == "--force":
            parsed["force"] = True
        elif a == "--outline-override":
            parsed["outline_override"] = True
        elif a in ("outline", "titles", "status", "rebuild", "recover", "prepare"):
            parsed["command"] = a
        elif a == "db":
            parsed["command"] = "db"
            if i + 1 < len(args) and args[i+1] in ("init", "stats"):
                i += 1; parsed["db_sub"] = args[i]
            else:
                parsed["db_sub"] = "stats"
        elif a == "scan" and i + 1 < len(args):
            parsed["command"] = "scan"
            i += 1; parsed["chapter"] = int(args[i])
        elif a == "promo":
            parsed["command"] = "promo"
            sub_types = ("synopsis","teaser","tags","author","cover","character","scene")
            if i + 1 < len(args) and args[i+1] in sub_types:
                i += 1; parsed["promo_type"] = args[i]
                if args[i] == "teaser" and i + 1 < len(args):
                    try: i += 1; parsed["chapter"] = int(args[i])
                    except: pass
                elif args[i] == "scene" and i + 1 < len(args):
                    try: i += 1; parsed["chapter"] = int(args[i])
                    except: pass
                elif args[i] == "character" and i + 1 < len(args):
                    try: i += 1; parsed["prompt"] = args[i]
                    except: pass
        elif a == "view":
            parsed["command"] = "view"
            if i + 1 < len(args) and args[i+1] in ("outline","titles","bible","chapter"):
                i += 1; parsed["view_target"] = args[i]
                if args[i] == "chapter" and i + 1 < len(args):
                    i += 1; parsed["chapter"] = int(args[i])
        elif a == "scan" and i + 1 < len(args):
            parsed["command"] = "scan"
            i += 1; parsed["chapter"] = int(args[i])
        elif a == "generate" and i + 1 < len(args):
            parsed["command"] = "generate"
            i += 1; parsed["chapter"] = int(args[i])
        elif a == "revise" and i + 1 < len(args):
            parsed["command"] = "revise"
            i += 1; parsed["chapter"] = int(args[i])
        elif a == "summary" and i + 1 < len(args):
            parsed["command"] = "summary"
            i += 1; parsed["volume"] = int(args[i])
        elif a in ("-p", "--prompt") and i + 1 < len(args):
            i += 1; parsed["prompt"] = args[i]
        elif a in ("-r", "--revise") and i + 1 < len(args):
            i += 1; parsed["prompt"] = args[i]
        elif not a.startswith("-") and parsed["command"] in ("revise",):
            parsed["content"] += (" " if parsed["content"] else "") + a
        elif a == "pending":
            parsed["command"] = "pending"
        elif a in ("publish", "discard") and i + 1 < len(args):
            parsed["command"] = a
            i += 1; parsed["chapter"] = int(args[i])
        i += 1
    return parsed


# ============================================================
# 命令实现
# ============================================================

def cmd_create(args):
    """创建独立的新小说工作区。"""
    from engine.novel_creator import create_novel, validate_slug, NOVELS_DIR as creation_root
    from engine.locking import novel_lock
    validate_slug(args["id"])
    with novel_lock(creation_root / args["id"]):
        path = create_novel(
            args["id"], args["title"], args["chapter_count"],
            args["words_per_chapter"], args["genre"], args["description"])
    print(f"小说已创建: {path}")


def cmd_list():
    """列出所有可用小说"""
    print("可用小说:")
    for d in sorted(NOVELS_DIR.iterdir()):
        if d.is_dir() and not d.name.startswith("."):
            title = d.name
            pf = d / "novel_prompts.json"
            if pf.exists():
                try:
                    meta = json.loads(pf.read_text(encoding="utf-8")).get("_meta", {})
                    title = meta.get("novel", d.name)
                except:
                    pass
            print(f"  {d.name:<20} {title}")


def cmd_db(sub: str):
    """数据库管理: db init → 从 bible 导入种子并建库"""
    from engine.db import NovelDB
    novel_dir = get_novel_dir()
    db = NovelDB(novel_dir)
    try:
        if sub == "init":
            counts = db.ensure_imported(force=True)
            parts = ", ".join(f"{k}={v}" for k, v in counts.items())
            print(f"知识库已导入: {db.path}")
            print(f"  {parts}")
        else:
            s = db.stats()
            print(f"  {get_novel()}: {db.path.name} ({s['db_bytes']:,} 字节)")
            for k in ("characters", "facts", "clues", "foreshadow_total",
                      "foreshadow_resolved", "lessons", "chapters_logged", "style_hits"):
                print(f"  {k:<20} {s[k]}")
    finally:
        db.close()


def cmd_scan(chapter_num: int):
    """对已生成章节做确定性风格扫描（不花 LLM 成本）"""
    from engine.style_kit import scanner
    config = get_config()
    cf = config.generated_dir / f"chapter_{chapter_num:02d}.md"
    if not cf.exists():
        print(f"错误: 第 {chapter_num} 章尚未生成")
        return
    text = cf.read_text(encoding="utf-8")
    r = scanner.scan(text)
    print(f"第 {chapter_num} 章 | {len(text):,} 字 | passed={r.passed}")
    print(f"指标: {json.dumps(r.metrics, ensure_ascii=False)}")
    if r.violations:
        print("违规:")
        for v in r.violations:
            print(f"  [{v['category']}] {v['pattern']} x{v['count']} @{v['where']} {v.get('hint','')}")
    for w in r.warnings:
        print(f"  [提示] {w['category']} {w['pattern']} x{w['count']} {w.get('hint','')}")


def cmd_status():
    """显示当前小说的创作进度"""
    config = get_config()
    novel_dir = get_novel_dir()
    gen_dir = config.generated_dir

    print(f"小说: {config.story_title} ({get_novel()})")
    print(f"总章节数: {config.chapter_count}")
    print(f"目录: {novel_dir}")

    existing = chapter_files(gen_dir)
    total_words = sum(len(f.read_text(encoding="utf-8")) for f in existing)
    vols = {}
    for f in existing:
        ch_num = parse_chapter_number(f)
        for vk, v in config.volume_config.items():
            lo, hi = v["chapters"]
            if lo <= ch_num <= hi:
                vols.setdefault(vk, []).append(ch_num)

    progress = len(existing)
    print(f"\n进度: {progress}/{config.chapter_count} ({progress*100//config.chapter_count}%)")
    print(f"总字数: {total_words:,}")
    print()

    for vk, v in config.volume_config.items():
        lo, hi = v["chapters"]
        done = len([c for c in (vols.get(vk, []))])
        pct = done * 100 // (hi-lo+1) if hi > lo else 0
        bar = "#" * (pct // 5) + "-" * (20 - pct // 5)
        print(f"  {v['name']}  [{bar}]  {done}/{hi-lo+1} ({pct}%)")

    clues_file = novel_dir / "bible" / "clues.json"
    if clues_file.exists():
        clues = json.loads(clues_file.read_text(encoding="utf-8"))
        active = clues.get("active_foreshadowing", {})
        pending_count = sum(1 for f in active.values() if f.get("status") == "pending")
        resolved = sum(1 for f in active.values() if f.get("status") == "resolved")
        print(f"\n伏笔: {resolved} 已回收 / {pending_count} 待回收 / {len(active)} 总计")

    # 待人工修订队列
    queue = pending.list_pending(config)
    if queue:
        latest = queue[-1]
        print(f"\n待人工修订: {len(queue)} 章 (revision/)")
        print(f"  最新: 第 {latest['num']} 章 | {latest.get('title') or '(未命名)'} | "
              f"{latest.get('words', 0):,} 字 | {latest.get('created_at', '')}")
        print(f"  处理: python novel.py --novel {get_novel()} publish/discard <章号>")
    else:
        print("\n待人工修订: 0 章")

    # 种子数据覆盖提醒：人物/线索/母题为空时，规划与写作缺少依据
    seeds = []
    for fname in ("characters.json", "clues.json", "motif_bank.json"):
        sf = novel_dir / "bible" / fname
        try:
            data = json.loads(sf.read_text(encoding="utf-8")) if sf.exists() else {}
            empty = (
                (fname == "characters.json" and not (data or {}).get("characters"))
                or (fname == "clues.json" and not (data or {}).get("active_foreshadowing"))
                or (fname == "motif_bank.json" and not (data or {}).get("motifs"))
            )
        except Exception:
            empty = True
        if empty:
            seeds.append(fname.replace(".json", ""))
    if seeds:
        print(f"[提示] 种子数据待补充: {', '.join(seeds)} 为空——建议先在 Web 设置页完善")


def cmd_view(args):
    """查看大纲、章名、或已生成章节"""
    config = get_config()
    target = args.get("view_target", "")

    if target == "outline":
        fp = config.bible_dir / "outline.md"
        if fp.exists():
            print(fp.read_text(encoding="utf-8")[:2000])
        else:
            print("尚未生成大纲。运行: python novel.py --novel {} outline".format(get_novel()))

    elif target == "titles":
        fp = config.bible_dir / "chapter_titles.json"
        if fp.exists():
            data = json.loads(fp.read_text(encoding="utf-8"))
            for vk, v in data.get("volumes", {}).items():
                print(f"\n{v['name']} (第{v['range'][0]}-{v['range'][1]}章)")
                for ch, title in sorted(v.get("chapters", {}).items(), key=lambda x: int(x[0])):
                    print(f"  {ch:>3}. {title}")
        else:
            print("尚未生成章名。运行: python novel.py --novel {} titles".format(get_novel()))

    elif target == "chapter":
        ch = args.get("chapter")
        if ch:
            fp = config.generated_dir / f"chapter_{ch:02d}.md"
            if fp.exists():
                print(fp.read_text(encoding="utf-8")[:2000])
            else:
                print(f"第 {ch} 章尚未生成")
        else:
            print("用法: python novel.py --novel X view chapter <N>")

    elif target == "bible":
        for fn in ["master_bible.md", "outline.md", "chapter_titles.json",
                    "characters.json", "clues.json", "motif_bank.json"]:
            fp = config.bible_dir / fn
            status = f"{fp.stat().st_size:,} 字节" if fp.exists() else "不存在"
            print(f"  {fn:<25} {status}")

    else:
        print("用法:")
        print("  python novel.py --novel X view outline    查看全书大纲")
        print("  python novel.py --novel X view titles     查看全部章名")
        print("  python novel.py --novel X view chapter N  查看第N章正文")
        print("  python novel.py --novel X view bible      查看知识库文件状态")


def cmd_promo(args):
    """生成宣传文案"""
    from engine.agents.marketer import MarketerAgent
    config = get_config()
    mk = MarketerAgent()

    bible = {}
    for fn in ["master_bible.md", "characters.json"]:
        fp = config.bible_dir / fn
        if fp.exists():
            bible[fp.stem] = json.loads(fp.read_text(encoding="utf-8")) if fp.suffix == ".json" else fp.read_text(encoding="utf-8")

    # 收集已写章节摘要
    gen_dir = config.generated_dir
    summaries = []
    for cf in chapter_files(gen_dir, limit=10):
        text = cf.read_text(encoding="utf-8")
        summaries.append(f"{cf.stem}: {text[:150]}...")
    summary_text = "\n".join(summaries) if summaries else "尚未生成章节"

    ptype = args.get("promo_type", "")

    if ptype == "synopsis":
        print(mk.synopsis(bible, summary_text))

    elif ptype == "teaser":
        ch = args.get("chapter", 1)
        tf = config.bible_dir / "chapter_titles.json"
        title = ""
        if tf.exists():
            data = json.loads(tf.read_text(encoding="utf-8"))
            for vol in data.get("volumes", {}).values():
                key = str(ch)
                if key in vol.get("chapters", {}):
                    title = vol["chapters"][key]; break
        cf = gen_dir / f"chapter_{ch:02d}.md"
        ch_summary = cf.read_text(encoding="utf-8")[:500] if cf.exists() else "未生成"
        print(mk.teaser(ch, title or f"第{ch}章", ch_summary))

    elif ptype == "tags":
        tags = mk.tags(bible, summary_text)
        print(" ".join(f"#{t}" for t in tags))

    elif ptype == "author":
        existing = chapter_files(gen_dir)
        progress = f"已更新 {len(existing)}/{config.chapter_count} 章，每天更新1-2章"
        print(mk.author_note(progress))

    elif ptype == "cover":
        bible_full = {"master_bible": "", "motif_bank": {}}
        for fn in ["master_bible.md", "motif_bank.json"]:
            fp = config.bible_dir / fn
            if fp.exists():
                bible_full[fp.stem] = json.loads(fp.read_text(encoding="utf-8")) if fp.suffix == ".json" else fp.read_text(encoding="utf-8")
        print(mk.cover_art(bible_full))

    elif ptype == "character":
        ch_name = args.get("prompt", "林泽")
        chars = bible.get("characters", {}).get("characters", {})
        profile = chars.get(ch_name, {})
        if not profile:
            print(f"人物 '{ch_name}' 不存在。可选: {', '.join(chars.keys())}")
        else:
            print(mk.character_portrait(ch_name, profile))

    elif ptype == "scene":
        ch = args.get("chapter", 1)
        print(mk.scene_illustration(ch))

    else:
        print("用法:")
        print("  python novel.py --novel X promo synopsis    小说简介")
        print("  python novel.py --novel X promo teaser N    第N章推荐语")
        print("  python novel.py --novel X promo tags        平台标签")
        print("  python novel.py --novel X promo author      作者的话")
        print("  python novel.py --novel X promo cover       封面图提示词")
        print("  python novel.py --novel X promo character N 人物立绘提示词")
        print("  python novel.py --novel X promo scene N     章节插图提示词")


class CommandError(RuntimeError):
    """可预期的命令业务失败。"""


class OutlineValidationError(CommandError):
    """模型连续返回无法安全解析的分卷大纲。"""


OUTLINE_PROTOCOL_VERSION = "2"


def outline_section_ranges(lo: int, hi: int, target_size: int = 10) -> list[tuple[int, int]]:
    """切成不超过12章的片；除最后一片外至少8章。"""
    if lo < 1 or hi < lo or target_size < 8 or target_size > 12:
        raise ValueError("大纲分片边界或 target_size 无效")
    total = hi - lo + 1
    if total <= 12:
        return [(lo, hi)]
    count = (total + target_size - 1) // target_size
    while count > 1 and total // count < 8:
        count -= 1
    sizes = [target_size] * (count - 1)
    sizes.append(total - sum(sizes))
    while sizes[-1] <= 0:
        sizes.pop()
    if len(sizes) > 1 and sizes[-1] > 12:
        sizes = []
        base, extra = divmod(total, count)
        sizes = [base + (1 if index < extra else 0) for index in range(count)]
    ranges = []
    start = lo
    for size in sizes:
        ranges.append((start, start + size - 1))
        start += size
    return ranges


def build_outline_prompt(title: str, volume: dict, bible: dict, user_prompt: str = "",
                         part_range: tuple[int, int] | None = None,
                         include_overview: bool = True,
                         volume_overview: str = "", previous_tail: str = "",
                         used_foreshadow_ids: list[str] | None = None) -> str:
    """构建单个大纲分片提示词，不依赖文件或模型调用。"""
    volume_lo, volume_hi = volume["chapters"]
    lo, hi = part_range or volume["chapters"]
    clues = bible.get("clues", {}).get("clues", {})
    foreshadowing = bible.get("clues", {}).get("active_foreshadowing", {})
    overview_template = (
        "### 卷概览\n这里写100-150字的单段卷概览，不换行。\n\n"
        if include_overview else ""
    )
    overview_rule = (
        "本片是本卷首片，必须从“### 卷概览”开始且概览只出现一次。"
        if include_overview else
        "本片不是首片，禁止输出“### 卷概览”及概览正文，必须直接从小节标题开始。"
    )
    prior_overview = f"\n【既定卷概览】{volume_overview}\n" if volume_overview else ""
    prior_tail = f"\n【上一片末2-3章】\n{previous_tail}\n" if previous_tail else ""
    used_ids = ", ".join(used_foreshadow_ids or []) or "无"
    ending_rule = (
        f"第{hi}章必须完成本卷收束。" if hi == volume_hi
        else f"第{hi}章只完成当前阶段并自然衔接第{hi + 1}章，不得提前收束全卷。"
    )
    result = (
        f"你是资深小说策划编辑。请为《{title}》{volume['name']}生成详细大纲。\n\n"
        f"【世界观】{bible.get('master_bible', '')[:2500]}\n\n"
        f"【本卷】{volume['name']}（第{volume_lo}-{volume_hi}章） | 情绪:{volume['core_emotion']} | 重点:{volume['focus']}\n"
        f"【当前分片】第{lo}-{hi}章，共{hi - lo + 1}章。{prior_overview}{prior_tail}\n"
        f"【人物】{json.dumps(bible.get('characters', {}), ensure_ascii=False, indent=2)[:2000]}\n\n"
        f"【线索池】{json.dumps({key: value.get('name', '') for key, value in clues.items()}, ensure_ascii=False)}\n"
        f"【伏笔池】{json.dumps({key: value.get('name', '') for key, value in foreshadowing.items()}, ensure_ascii=False)}\n"
        f"【已用伏笔ID】{used_ids}\n\n"
        "【输出边界】\n"
        f"只输出{volume['name']}的卷内容中第{lo}-{hi}章，不要输出或重复“## {volume['name']}”这类卷标题。"
        "不要输出前言、结语、自查结果、卷总结标题或其他说明。\n\n"
        "【精确模板】\n" + overview_template +
        "### 第N-M章：小节名\n"
        "- **第N章 章名**：核心剧情（明确谁做什么导致什么）。*功能：该章的结构功能；伏笔：引入 F001*\n\n"
        "【硬性规则】\n"
        f"1. 必须且只能输出第{lo}章至第{hi}章，恰好{hi - lo + 1}行章节 bullet，每个章号恰好出现一次、连续升序，禁止跳号、重复或越界。\n"
        "2. 每章严格占一行，并严格使用模板中的顶层 bullet；章名2-6字；核心剧情必须明确谁做什么导致什么。\n"
        "3. 功能字段必填；伏笔字段只能写“引入 Fxxx”“推进 Fxxx”“回收 Fxxx”或“无”，Fxxx为三位数字编号。\n"
        "4. 小节标题范围必须与下方章节一致；当前分片通常就是一个8-12章小节。\n"
        "5. 禁止在章节下添加二级 bullet、Markdown代码块或额外标题；禁止在末尾追加任何说明、总结或未完待续文字，最后一行必须是第{hi}章。\n"
        f"6. {overview_rule}{ending_rule}写完本片最后一章立即结束。\n"
        f"【自检】逐行核对：每行只能是“### 第N-M章：小节名”或标准章节 bullet；第{lo}至第{hi}章必须全部出现、恰一次、按序连续；不得多出或缺少任何行。只要有一行不合规，本片即作废。"
    )
    if user_prompt:
        result += f"\n\n【用户要求】{user_prompt}"
    return result


def validate_outline_output(content: str, lo: int, hi: int,
                            include_overview: bool = True) -> list[str]:
    """校验单个大纲分片，返回可直接反馈给模型的具体错误。"""
    errors = []
    lines = content.strip().splitlines()
    nonempty = [(index + 1, line) for index, line in enumerate(lines) if line.strip()]
    overview_heading = [(number, line) for number, line in nonempty if line == "### 卷概览"]
    expected_overviews = 1 if include_overview else 0
    if len(overview_heading) != expected_overviews:
        errors.append(f"“### 卷概览”应恰好出现{expected_overviews}次，实际{len(overview_heading)}次")
    if not include_overview and nonempty and not nonempty[0][1].startswith("### 第"):
        errors.append("非首片必须直接从小节标题开始")

    if any(re.match(r"^##(?:\s|$)", line) for _, line in nonempty):
        errors.append("包含禁止的H2卷标题（## ...），不要重复程序生成的卷标题")
    if "自查" in content:
        errors.append("包含禁止的自查文本")

    overview_line = None
    if overview_heading:
        heading_position = next(i for i, item in enumerate(nonempty) if item[0] == overview_heading[0][0])
        if heading_position != 0:
            errors.append("输出必须从“### 卷概览”开始")
        if heading_position + 1 >= len(nonempty):
            errors.append("缺少卷概览正文")
        else:
            overview_line = nonempty[heading_position + 1]
            overview_length = len(overview_line[1].strip())
            if not 100 <= overview_length <= 150:
                errors.append(f"卷概览必须为100-150字单段，实际{overview_length}字")
            if overview_line[1].lstrip().startswith(("#", "-", "*")):
                errors.append("卷概览正文必须是普通单段，不能使用标题或列表")

    section_re = re.compile(r"^### 第(\d+)-(\d+)章：([^\n]+)$")
    chapter_re = re.compile(
        r"^- \*\*第(\d+)章 ([^*\n]+)\*\*：(.+)。\*功能：([^*\n；]+(?:；[^*\n]+)*?)；"
        r"伏笔：(?:(引入|推进|回收) (F\d{3})|无)\*$"
    )
    sections = []
    chapters = []
    unexpected = []
    current_section = None

    for line_number, line in nonempty:
        if line == "### 卷概览" or (overview_line and line_number == overview_line[0]):
            continue
        section_match = section_re.fullmatch(line)
        if section_match:
            current_section = {
                "lo": int(section_match.group(1)),
                "hi": int(section_match.group(2)),
                "line": line_number,
                "chapters": [],
            }
            sections.append(current_section)
            continue
        chapter_match = chapter_re.fullmatch(line)
        if chapter_match:
            chapter_number = int(chapter_match.group(1))
            chapters.append(chapter_number)
            if current_section is None:
                errors.append(f"第{line_number}行章节前缺少小节标题")
            else:
                current_section["chapters"].append(chapter_number)
            continue
        unexpected.append(line_number)

    if unexpected:
        shown = "、".join(str(number) for number in unexpected[:10])
        errors.append(f"第{shown}行不符合允许格式（只接受小节标题和顶层单行章节bullet）")
    if not sections:
        errors.append("至少需要一个“### 第N-M章：小节名”小节")

    expected = set(range(lo, hi + 1))
    counts = {number: chapters.count(number) for number in set(chapters)}
    missing = sorted(expected - set(chapters))
    duplicates = sorted(number for number, count in counts.items() if count > 1)
    out_of_range = sorted(set(chapters) - expected)
    if missing:
        errors.append("缺失章号：" + "、".join(map(str, missing)))
    if duplicates:
        errors.append("重复章号：" + "、".join(map(str, duplicates)))
    if out_of_range:
        errors.append("越界章号：" + "、".join(map(str, out_of_range)))
    if chapters and chapters != list(range(lo, hi + 1)):
        errors.append(f"章节必须按第{lo}章至第{hi}章连续升序排列")

    for index, section in enumerate(sections):
        section_expected = list(range(section["lo"], section["hi"] + 1))
        if section["lo"] < lo or section["hi"] > hi or section["lo"] > section["hi"]:
            errors.append(f"第{section['line']}行小节范围越界或倒置：{section['lo']}-{section['hi']}")
        if section["chapters"] != section_expected:
            errors.append(
                f"第{section['line']}行小节范围{section['lo']}-{section['hi']}与其下章节"
                f"{section['chapters'] or '空'}不一致"
            )
        size = section["hi"] - section["lo"] + 1
        is_last = index == len(sections) - 1
        if hi - lo + 1 < 8:
            if len(sections) != 1 or section["lo"] != lo or section["hi"] != hi:
                errors.append("本卷少于8章时必须整卷使用一个小节")
        elif size > 12 or (size < 8 and not is_last):
            errors.append(f"第{section['line']}行小节应为8-12章，仅最后一节可少于8章")

    if sections:
        ranges = [(section["lo"], section["hi"]) for section in sections]
        expected_start = lo
        for start, end in ranges:
            if start != expected_start:
                errors.append(f"小节范围不连续：期望从第{expected_start}章开始，实际从第{start}章开始")
                break
            expected_start = end + 1
        if expected_start != hi + 1:
            errors.append(f"小节范围未覆盖至第{hi}章")

    return list(dict.fromkeys(errors))


def _outline_corrective_example(errors: list[str]) -> str:
    """从校验错误中找出缺失章号，返回一个可直接照抄的格式示范。

    模型常在长篇靠后的分片漏掉末尾章节，并把最后两行写成说明或残缺格式。
    给出缺失章号的标准行模板，比只告诉它“缺失章号：149、150”更容易纠正。
    """
    missing: list[int] = []
    for error in errors:
        if error.startswith("缺失章号："):
            missing = [int(number) for number in re.findall(r"\d+", error)]
            break
    if not missing:
        return ""
    sample_lines = []
    for index, number in enumerate(missing[:2]):
        if index == 0:
            plot, function = "主角率盟友反攻并夺回关键物品，切断幕后势力退路。", "阶段收束并衔接下文"
        else:
            plot, function = "主角清点残局、收拢各方，为下一阶段冲突埋下引线。", "收束本阶段并为后续铺垫"
        sample_lines.append(f"- **第{number}章 收束**：{plot}*功能：{function}；伏笔：无*")
    sample = "\n".join(sample_lines)
    return (
        "\n\n【缺失章节正确格式示范】章名、剧情请换成贴合本片的2-6字与情节，"
        "但行首“- **第X章 ”、行中“*功能：”与“；伏笔：无*”的标点格式必须完全一致：\n"
        + sample
    )


def _generate_valid_outline_part(chat, model, initial_prompt: str, lo: int, hi: int,
                                 include_overview: bool = True,
                                 on_attempt=None) -> tuple[str, int] | str:
    prompt = initial_prompt
    last_errors = []
    for attempt in range(1, 6):
        if on_attempt:
            on_attempt(attempt)
        part = chat(model, user_prompt=prompt).strip()
        last_errors = validate_outline_output(part, lo, hi, include_overview)
        if not last_errors:
            return (part, attempt) if on_attempt else part
        if attempt < 5:
            feedback = "\n".join(f"- {error}" for error in last_errors)
            prompt = (
                initial_prompt
                + "\n\n【上次输出未通过格式校验】\n"
                + feedback
                + _outline_corrective_example(last_errors)
                + "\n请修正全部问题并重新输出完整分片，不要解释。\n\n【上次输出】\n"
                + part
            )
    raise OutlineValidationError(
        f"第{lo}-{hi}章大纲连续5次格式不合格：" + "；".join(last_errors)
        + "。已完成的其他分片均已保存，重试本命令会自动跳过它们、只重新生成失败分片。"
    )


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
                Path(temp_name).unlink()
            except OSError:
                pass


def _outline_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _save_outline_manifest(path: Path, records: dict, outline_state: dict | None = None):
    payload = {
        "version": 2,
        "protocol_version": OUTLINE_PROTOCOL_VERSION,
        "outline": outline_state or {"status": "generating", "invalid": True},
        "parts": list(records.values()),
    }
    _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2))


def mark_outline_manual(bible_dir: Path, content: str):
    manifest_path = bible_dir / "outline_manifest.json"
    records = {}
    if manifest_path.exists():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            records = {f"{item['volume']}:{item['range'][0]}-{item['range'][1]}": item
                       for item in loaded.get("parts", [])}
        except (OSError, ValueError, KeyError, TypeError):
            records = {}
    _save_outline_manifest(manifest_path, records, {
        "status": "manual", "invalid": True, "manual_hash": _outline_hash(content),
    })


def _outline_input_hash(title: str, volume_key: str, volume: dict, bible: dict,
                        user_prompt: str, previous_part_hash: str,
                        volume_overview: str) -> str:
    payload = {
        "protocol_version": OUTLINE_PROTOCOL_VERSION,
        "user_prompt": user_prompt,
        "title": title,
        "volume_key": volume_key,
        "volume": volume,
        "master_bible": bible.get("master_bible", ""),
        "characters": bible.get("characters", {}),
        "clues": bible.get("clues", {}),
        "motifs": bible.get("motif_bank", {}),
        "previous_part_hash": previous_part_hash,
        "volume_overview": volume_overview,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _outline_hash(canonical)


def _outline_tail(part: str, count: int = 3) -> str:
    chapter_lines = [line for line in part.splitlines()
                     if re.match(r"^- \*\*第\d+章 ", line)]
    return "\n".join(chapter_lines[-count:])


def cmd_outline(prompt="", force=False):
    """按分片生成全书大纲；默认安全续跑，force 全量重建。"""
    config = get_config()
    config.bible_dir.mkdir(parents=True, exist_ok=True)
    bible = {}
    for fn in ["master_bible.md", "characters.json", "clues.json", "motif_bank.json"]:
        fp = config.bible_dir / fn
        if fp.exists():
            bible[fp.stem] = (json.loads(fp.read_text(encoding="utf-8"))
                              if fp.suffix == ".json" else fp.read_text(encoding="utf-8"))

    from engine.llm_client import chat

    manifest_path = config.bible_dir / "outline_manifest.json"
    outline_file = config.bible_dir / "outline.md"
    records = {}
    loaded = {}
    if manifest_path.exists():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            records = {f"{item['volume']}:{item['range'][0]}-{item['range'][1]}": item
                       for item in loaded.get("parts", [])}
        except (OSError, ValueError, KeyError, TypeError):
            records = {}
            loaded = {}
    if loaded.get("outline", {}).get("status") == "manual" and not force:
        raise CommandError("outline.md 已人工修改，普通 resume 不会覆盖；请审阅后使用 outline --force 明确重生成")
    if force and outline_file.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup = outline_file.with_name(f"outline.{stamp}.bak.md")
        _atomic_write(backup, outline_file.read_text(encoding="utf-8"))
        print(f"已备份现有大纲: {backup}")

    state = {"status": "generating", "invalid": True}
    assembled_volumes = []
    previous_chain_hash = ""
    previous_tail = ""
    used_foreshadow_ids = set()
    active_keys = []
    for volume_key, volume in config.volume_config.items():
        volume_lo, volume_hi = volume["chapters"]
        volume_parts = []
        volume_overview = ""
        for index, (lo, hi) in enumerate(outline_section_ranges(volume_lo, volume_hi)):
            include_overview = index == 0
            relative = f"outline_parts/{volume_key}/section_{lo}_{hi}.md"
            part_path = config.bible_dir / relative
            record_key = f"{volume_key}:{lo}-{hi}"
            active_keys.append(record_key)
            existing = part_path.read_text(encoding="utf-8").strip() if part_path.exists() else ""
            input_hash = _outline_input_hash(
                config.story_title, volume_key, volume, bible, prompt,
                previous_chain_hash, volume_overview)
            old_record = records.get(record_key, {})
            output_hash = _outline_hash(existing) if existing else ""
            reusable = (
                not force and old_record.get("status") == "complete"
                and bool(existing)
                and not validate_outline_output(existing, lo, hi, include_overview)
                and old_record.get("hash") == output_hash
                and old_record.get("input_hash") == input_hash
            )
            if reusable:
                part = existing
                attempts = old_record.get("attempt", 0)
                print(f"跳过匹配分片 {volume['name']} 第{lo}-{hi}章")
            else:
                print(f"生成 {volume['name']} 第{lo}-{hi}章 ...")
                part_prompt = build_outline_prompt(
                    config.story_title, volume, bible, prompt, (lo, hi),
                    include_overview, volume_overview, previous_tail,
                    sorted(used_foreshadow_ids))

                def mark_attempt(attempt, key=record_key, rel=relative,
                                 expected_input=input_hash):
                    records[key] = {
                        "volume": volume_key, "range": [lo, hi], "status": "running",
                        "attempt": attempt, "hash": "", "input_hash": expected_input,
                        "chain_hash": "", "path": rel,
                    }
                    _save_outline_manifest(manifest_path, records, state)
                try:
                    part, attempts = _generate_valid_outline_part(
                        chat, config.planner_model, part_prompt, lo, hi,
                        include_overview, mark_attempt)
                except Exception:
                    records[record_key]["status"] = "failed"
                    _save_outline_manifest(manifest_path, records, state)
                    raise
                _atomic_write(part_path, part)
                output_hash = _outline_hash(part)
            chain_hash = _outline_hash(input_hash + ":" + output_hash)
            records[record_key] = {
                "volume": volume_key, "range": [lo, hi], "status": "complete",
                "attempt": attempts, "hash": output_hash, "input_hash": input_hash,
                "chain_hash": chain_hash, "path": relative,
            }
            _save_outline_manifest(manifest_path, records, state)
            if include_overview:
                nonempty = [line.strip() for line in part.splitlines() if line.strip()]
                volume_overview = nonempty[1] if len(nonempty) > 1 else ""
            used_foreshadow_ids.update(re.findall(r"\bF\d{3}\b", part))
            previous_tail = _outline_tail(part)
            previous_chain_hash = chain_hash
            volume_parts.append(part)
        assembled_volumes.append(
            f"## {volume['name']}（第{volume_lo}-{volume_hi}章）\n" +
            "\n\n".join(volume_parts))

    outline = f"# {config.story_title} — 全书大纲\n\n" + "\n\n".join(assembled_volumes)
    _atomic_write(outline_file, outline)
    records = {key: records[key] for key in active_keys}
    state = {"status": "generated", "invalid": False, "hash": _outline_hash(outline)}
    _save_outline_manifest(manifest_path, records, state)
    print(f"大纲已保存: {outline_file} ({len(outline)} 字符)")
    print("请审阅。修改后运行: python novel.py --novel {} titles".format(get_novel()))


def _parse_titles_from_outline(outline: str) -> dict:
    """从大纲文本提取章名"""
    import re
    titles_by_vol = {}
    current_vol = None
    for line in outline.split("\n"):
        vol_match = re.match(r'^##\s+(?:第.+卷[：:]?\s*)?(.+?)[（(]第(\d+)-(\d+)章[)）]', line)
        if vol_match:
            current_vol = f"volume_{len(titles_by_vol)+1}"
            titles_by_vol[current_vol] = {}
            continue
        ch_match = re.match(r'^[-*]\s*\*?\*?第(\d+)章\s+(.+?)\*?\*?\s*[：:]', line)
        if ch_match and current_vol:
            titles_by_vol[current_vol][ch_match.group(1)] = ch_match.group(2).strip()
    return titles_by_vol


def cmd_titles(prompt=""):
    """从大纲文件提取全部章名 → bible/chapter_titles.json"""
    import re
    config = get_config()

    outline_file = config.bible_dir / "outline.md"
    if not outline_file.exists():
        raise CommandError(
            "未找到 bible/outline.md，请先运行: python novel.py --novel {} outline".format(get_novel())
        )

    outline = outline_file.read_text(encoding="utf-8")

    # 有 --prompt 时用 LLM 生成；否则直接从大纲解析
    if prompt:
        from engine.llm_client import chat_json
        from engine.prompts_loader import get_prompt
        system, _ = get_prompt("title_generator")
        system = system.format(outline=outline)
        system += f"\n\n【用户要求】{prompt}"
        print("LLM 生成章名中...")
        titles_by_vol = chat_json(config.planner_model, user_prompt=system)
        if not isinstance(titles_by_vol, dict) or not titles_by_vol:
            print("LLM 返回异常，回退到直接解析模式")
            titles_by_vol = _parse_titles_from_outline(outline)
    else:
        titles_by_vol = _parse_titles_from_outline(outline)

    if not titles_by_vol or not isinstance(titles_by_vol, dict):
        raise CommandError(
            "未能从 outline.md 提取章名；请检查大纲格式或使用 titles -p '要求'"
        )

    total_new = sum(len(v) for v in titles_by_vol.values() if isinstance(v, dict))

    # 读取已有章名（如果有的话），合并而非覆盖
    titles_file = config.bible_dir / "chapter_titles.json"
    existing = {}
    if titles_file.exists():
        try:
            existing_data = json.loads(titles_file.read_text(encoding="utf-8"))
            for vk, v in existing_data.get("volumes", {}).items():
                existing[vk] = v.get("chapters", {})
        except:
            pass

    result = {"_schema": "1.0", "_description": "章节标题库", "volumes": {}}
    for vk, v in config.volume_config.items():
        lo, hi = v["chapters"]
        # 优先用已存在的，新 LLM 结果只做增量合并
        merged = dict(existing.get(vk, {}))
        vol_chapters = titles_by_vol.get(vk, {})
        if isinstance(vol_chapters, dict):
            merged.update(vol_chapters)

        result["volumes"][vk] = {
            "name": v["name"],
            "range": v["chapters"],
            "synopsis": v["focus"],
            "chapters": dict(sorted(merged.items(), key=lambda x: int(x[0])))
        }

    total = sum(len(v['chapters']) for v in result['volumes'].values())

    # 自动补全缺失章名
    missing = []
    for vk, v in config.volume_config.items():
        lo, hi = v["chapters"]
        vol_chapters = result["volumes"][vk]["chapters"]
        for ch_num in range(lo, hi + 1):
            key = str(ch_num)
            if key not in vol_chapters:
                auto_title = f"第{ch_num}章"
                vol_chapters[key] = auto_title
                missing.append(f"  {vk} 第{ch_num}章 → 「{auto_title}」(自动填充)")
        result["volumes"][vk]["chapters"] = dict(sorted(vol_chapters.items(), key=lambda x: int(x[0])))

    total = sum(len(v['chapters']) for v in result['volumes'].values())
    titles_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    if missing:
        print(f"\n  ⚠ 自动补全 {len(missing)} 章:")
        for m in missing[:10]:
            print(m)
        if len(missing) > 10:
            print(f"  ... 等共 {len(missing)} 章")
        print(f"  章名已保存: {titles_file} ({total}/{config.chapter_count} 章)")
        print(f"  请手动修改自动填充的章名: python novel.py --novel {get_novel()} view titles")
    elif prompt:
        print(f"章名已保存: {titles_file} ({total} 章, 本次新增 {total_new} 章)")
    else:
        print(f"章名已保存: {titles_file} ({total}/{config.chapter_count} 章)")


class SceneQualityError(RuntimeError):
    """场景在限定重试次数内未通过全部质量闸门。"""


def _save_failed_draft(config, chapter_num: int, scene_id, draft: str,
                       diagnostics: dict) -> Path:
    failed_dir = config.cache_dir / "failed_drafts"
    failed_dir.mkdir(parents=True, exist_ok=True)
    safe_scene_id = re.sub(r"[^0-9A-Za-z_-]+", "_", str(scene_id))
    stem = f"chapter_{chapter_num:02d}_scene_{safe_scene_id}"
    target = failed_dir / f"{stem}.md"
    target.write_text(draft, encoding="utf-8")
    (failed_dir / f"{stem}.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return target


def planning_readiness(config) -> dict:
    if not hasattr(config, "chapter_count"):
        return {"outline_ready": True, "outline_numbers": set(), "outline_entries": 0,
                "titles_ready": True, "titles": {}, "placeholders": [],
                "missing_outline": [], "missing_titles": []}
    expected = set(range(1, config.chapter_count + 1))
    outline_file = config.bible_dir / "outline.md"
    outline_text = outline_file.read_text(encoding="utf-8") if outline_file.exists() else ""
    outline_numbers = [int(number) for number in re.findall(
        r"(?m)^[-*]\s*\*?\*?第(\d+)章\s+", outline_text)]
    outline_set = set(outline_numbers)
    outline_ready = outline_set == expected and len(outline_numbers) == len(expected)

    titles = {}
    titles_file = config.bible_dir / "chapter_titles.json"
    if titles_file.exists():
        try:
            data = json.loads(titles_file.read_text(encoding="utf-8"))
            for volume in data.get("volumes", {}).values():
                for raw_number, title in volume.get("chapters", {}).items():
                    titles[int(raw_number)] = str(title).strip()
        except (OSError, ValueError, TypeError, AttributeError):
            titles = {}
    placeholders = sorted(number for number, title in titles.items()
                          if not title or re.fullmatch(r"第?\d+章", title))
    title_numbers = set(titles)
    titles_ready = title_numbers == expected and not placeholders
    return {
        "outline_ready": outline_ready,
        "outline_numbers": outline_set,
        "outline_entries": len(outline_numbers),
        "titles_ready": titles_ready,
        "titles": titles,
        "placeholders": placeholders,
        "missing_outline": sorted(expected - outline_set),
        "missing_titles": sorted(expected - title_numbers),
    }


def cmd_generate(chapter_num: int, instruction: str = "", overwrite: bool = False,
                 outline_override: bool = False):
    """生成单章；默认要求完整大纲和非占位章名。"""
    from engine.agents.planner import PlannerAgent
    from engine.agents.researcher import ResearcherAgent
    from engine.agents.writer import WriterAgent
    from engine.agents.reviewers import ReviewerAgent
    from engine.agents.keeper import KeeperAgent
    from engine.agents.archivist import ArchivistAgent
    from engine.agents.dialogue_auditor import DialogueAuditor
    from engine.agents.foreshadowing_steward import ForeshadowingSteward
    from engine.agents.reader_proxy import ReaderProxy
    from engine.agents.story_keeper import StoryKeeperAgent

    config = get_config()
    if not outline_override:
        readiness = planning_readiness(config)
        if not readiness["outline_ready"]:
            raise CommandError("写作门禁：全书大纲未按章号完整覆盖；如确需跳过请显式使用 --outline-override")
        if not readiness["titles_ready"]:
            raise CommandError("写作门禁：章名未完整生成或仍含“第N章”占位名；如确需跳过请显式使用 --outline-override")
    from engine.knowledge import check_ready
    try:
        check_ready(config, chapter_num)
    except ValueError as exc:
        raise CommandError(str(exc)) from exc
    chapter_file = config.generated_dir / f"chapter_{chapter_num:02d}.md"
    replacing = chapter_file.exists()
    if replacing and not overwrite:
        raise FileExistsError(
            f"第 {chapter_num} 章已存在；如需覆盖请显式传入 --overwrite"
        )
    if replacing:
        # Replanning an old chapter from the latest Bible would leak future state.
        return cmd_revise(chapter_num, instruction or "优化本章目标、因果、节奏与回报，保留已发生的核心事件。")
    planner = PlannerAgent()
    researcher = ResearcherAgent()
    writer = WriterAgent()
    reviewers = ReviewerAgent()
    keeper = KeeperAgent()
    archivist = ArchivistAgent()
    auditor = DialogueAuditor()
    steward = ForeshadowingSteward()
    reader = ReaderProxy()
    story_keeper = StoryKeeperAgent()

    for d in [config.bible_dir, config.generated_dir, config.cache_dir,
              pending.revision_dir(config)]:
        d.mkdir(parents=True, exist_ok=True)

    # Bible + lessons
    bible = {}
    for fn in ["master_bible.md", "characters.json", "clues.json", "motif_bank.json"]:
        fp = config.bible_dir / fn
        if fp.exists():
            bible[fp.stem] = json.loads(fp.read_text(encoding="utf-8")) if fp.suffix == ".json" else fp.read_text(encoding="utf-8")

    lp = config.bible_dir / "lessons_learned.jsonl"
    lessons = []
    if lp.exists():
        for line in lp.read_text(encoding="utf-8").strip().split("\n"):
            line = line.strip()
            if line:
                try: lessons.append(json.loads(line))
                except: pass
    lessons = lessons[-5:]

    # 加载锁定的章名
    tf = config.bible_dir / "chapter_titles.json"
    locked_title = ""
    if tf.exists():
        data = json.loads(tf.read_text(encoding="utf-8"))
        for vol in data.get("volumes", {}).values():
            key = str(chapter_num)
            if key in vol.get("chapters", {}):
                locked_title = vol["chapters"][key]
                break

    print(f"当前小说: {config.story_title}  第 {chapter_num} 章: {locked_title}")
    log.info(f"=== 第 {chapter_num} 章 开始 ===")

    from engine import checkpoint
    checkpoint_file = checkpoint.checkpoint_path(config, chapter_num, instruction, locked_title)
    resumed = checkpoint.load(checkpoint_file)
    plan_json = (resumed["plan"] if resumed else planner.run(
        chapter_num, instruction or f"继续推进第{chapter_num}章剧情", bible, lessons, locked_title))
    log.info(f"大纲: {plan_json.get('chapter_title','')} ({len(plan_json.get('scene_outline',[]))} 场景)")

    # 伏笔管家审计大纲；确定性严重错误会在任何正文生成前抛出。
    steward_result = steward.audit(plan_json, chapter_num, bible)
    if steward_result.get("operation_warnings"):
        log.warning(f"伏笔管家警告: {steward_result['operation_warnings']}")
    reminders = steward_result.get("reminders", [])
    if reminders:
        plan_json["foreshadowing_reminders"] = reminders
        print(f"  [伏笔管家] 提醒: {reminders}")

    context_pack = researcher.run(plan_json, chapter_num, bible)
    context_pack["_plan"] = plan_json
    previous_file = config.generated_dir / f"chapter_{chapter_num - 1:02d}.md"
    if previous_file.exists():
        context_pack["previous_chapter_tail"] = previous_file.read_text(encoding="utf-8")[-1600:]
    if reminders:
        context_pack["foreshadowing_reminders"] = reminders
        context_pack["research_notes"] = (
            context_pack.get("research_notes", "")
            + "\n\n## 伏笔管家提醒（规划与写作必须处理）\n"
            + "\n".join(f"- {item}" for item in reminders)
        ).strip()

    keeper_cache = resumed["keeper_cache"] if resumed else keeper.init_cache(chapter_num)

    # 故事全局状态：把开放问题/未回收承诺/角色弧线/连续性警告注入本次生成上下文
    try:
        from engine.agents.story_keeper import load_bare_state, planner_context, writer_warnings
        story_state = load_bare_state(config.bible_dir)
        context_pack["story_state_text"] = planner_context(story_state, chapter_num, plan_json)
        context_pack["story_continuity_warnings"] = writer_warnings(story_state, chapter_num, plan_json)
        context_pack["_story_state"] = story_state  # 供 story_check 故事逻辑闸门做结构化对账
        if context_pack["story_continuity_warnings"]:
            log.info(f"StoryKeeper 注入本章 {len(context_pack['story_continuity_warnings'])} 字故事状态约束")
    except Exception as e:
        log.warning(f"StoryKeeper 状态注入失败: {e}")

    from engine.style_kit import scanner
    feedback_map = {}
    scene_failures = resumed["scene_failures"] if resumed else []
    completed = resumed["completed"] if resumed else 0
    if completed > len(plan_json.get("scene_outline", [])):
        raise CommandError("写作检查点的场景进度无效")
    if resumed:
        print(f"从检查点恢复：已有 {completed} 个完整场景，输入版本一致")
    checkpoint.save(checkpoint_file, plan_json, keeper_cache, completed, scene_failures)
    for index, scene in enumerate(plan_json.get("scene_outline", [])):
        if index < completed:
            continue
        sid = scene.get("scene_id", "?")
        max_retries = config.immediate_review_max_retries
        accepted = False
        draft = ""
        best_draft = ""
        best_diagnostics = {}
        best_score = None
        diagnostics = {}
        for attempt in range(max_retries + 1):
            context_pack["revision_draft"] = draft
            draft = writer.run(
                scene, keeper_cache, context_pack, chapter_num,
                feedback_map.get(sid, ""),
            )
            scan_result = scanner.scan(draft)
            review = reviewers.immediate_check(
                draft, scene, keeper_cache, context_pack,
            )
            audit = auditor.audit(
                draft, context_pack, scene.get("type", "high_conflict"),
            )
            # 故事逻辑闸门：草稿是否与既有跨章事实矛盾、是否无视承诺/钩子/开放问题
            from engine.agents.story_keeper import story_check
            story_result = story_check(
                context_pack.get("_story_state") or {},
                chapter_num, scene, draft, keeper_cache,
            )
            story_passed = story_result.get("passed", False) is True
            accepted = (
                scan_result.passed
                and review.get("passed", False) is True
                and audit.get("passed", False) is True
                and story_passed
            )
            diagnostics = {
                "attempt": attempt + 1,
                "scan_passed": scan_result.passed,
                "scan_violations": scan_result.violations,
                "review_passed": review.get("passed", False) is True,
                "review": review,
                "dialogue_passed": audit.get("passed", False) is True,
                "dialogue_audit": audit,
                "story_passed": story_passed,
                "story_check": story_result,
            }
            # 记录闸门总分最接近通过的一稿，供重试耗尽时降级接受
            score = (
                len(scan_result.violations) * 100
                + (10 if not scan_result.passed else 0)
                + (10 if review.get("passed", False) is not True else 0)
                + len(review.get("errors", []) or [])
                + (10 if audit.get("passed", False) is not True else 0)
                + len(audit.get("violations", []) or [])
                + (10 if not story_passed else 0)
                + len(story_result.get("errors", []) or [])
            )
            if best_score is None or score <= best_score:
                best_score = score
                best_draft = draft
                best_diagnostics = dict(diagnostics)
            if accepted:
                break
            suggestions = [
                scan_result.to_suggestions(),
                review.get("suggestions", ""),
                audit.get("suggestions", ""),
                story_result.get("suggestions", ""),
            ]
            feedback_map[sid] = "；".join(item for item in suggestions if item)
            log.warning(
                f"  场景 {sid} 第{attempt + 1}轮未通过全部质量闸门"
            )

        if not accepted:
            # 重试耗尽：保存最佳稿诊断供事后审阅（attempt 级审计），继续按最佳稿合并。
            # 若最终仍不过闸门，整章转入待人工修订队列，由作家定稿。
            failed_path = _save_failed_draft(
                config, chapter_num, sid, best_draft, best_diagnostics,
            )
            scene_failures.append({
                "scene_id": sid,
                "attempts": max_retries + 1,
                "gates": {
                    "scan_passed": bool(best_diagnostics.get("scan_passed", False)),
                    "review_passed": bool(best_diagnostics.get("review_passed", False)),
                    "dialogue_passed": bool(best_diagnostics.get("dialogue_passed", False)),
                    "story_passed": bool(best_diagnostics.get("story_passed", False)),
                },
                "best_score": best_score,
            })
            log.warning(
                f"  场景 {sid} 重试 {max_retries + 1} 轮未过全部质量闸门"
                f"（将转入待人工修订，诊断已存: {failed_path}）"
            )
            draft = best_draft
        keeper_cache = keeper.update(keeper_cache, draft, chapter_num, sid)
        checkpoint.save(checkpoint_file, plan_json, keeper_cache, index + 1, scene_failures)

    all_scenes = keeper_cache.get("all_scenes", [])
    full_chapter = writer.merge_scenes(all_scenes, plan_json, chapter_num)
    final_scan = scanner.scan(full_chapter)

    if chapter_num % config.heavy_review_interval == 0:
        heavy = reviewers.heavy_check(full_chapter, plan_json, chapter_num)
        if heavy.get("patch_instructions"):
            log.warning(f"重型审查: {heavy.get('score','?')}分, {len(heavy['patch_instructions'])} 条指示")
            patched = writer.apply_patches(full_chapter, plan_json, heavy["patch_instructions"], chapter_num)
            patched_scan = scanner.scan(patched)
            before_weight = len(final_scan.violations) * 100 + len(final_scan.warnings)
            after_weight = len(patched_scan.violations) * 100 + len(patched_scan.warnings)
            metrics_worse = (
                patched_scan.metrics.get("max_same_len_run", 0)
                > final_scan.metrics.get("max_same_len_run", 0)
            )
            final_heavy = reviewers.heavy_check(patched, plan_json, chapter_num)
            still_needs_patch = bool(final_heavy.get("patch_instructions"))
            if (patched_scan.violations or after_weight > before_weight
                    or metrics_worse or still_needs_patch):
                log.warning("补丁未通过最终审阅或扫描结果更差，保留补丁前正文")
            else:
                full_chapter = patched
                final_scan = patched_scan
                keeper_cache = keeper.reconcile_final_chapter(
                    keeper_cache, full_chapter, chapter_num,
                )
    else:
        heavy = {"score": None, "patch_instructions": []}

    from engine.quality import edit_chapter
    full_chapter, final_scan, reader_result, chapter_reviews, chapter_passed = edit_chapter(
        full_chapter, plan_json, chapter_num, context_pack, config,
        writer, reviewers, reader, auditor,
    )
    if chapter_passed:
        keeper_cache = keeper.reconcile_final_chapter(keeper_cache, full_chapter, chapter_num)
        keeper_cache["_reader_result"] = reader_result

    style_hits = final_scan.to_rows(chapter_num)
    keeper_cache["_style_hits"] = style_hits
    if style_hits:
        print(f"  [风格扫描] 最终正文命中风格问题 {len(style_hits)} 条")

    # 全部闸门通过 → 正常发布；否则按 GATE_FAIL_MODE 转入待修订队列或硬失败。
    if chapter_passed and final_scan.passed:
        # Keep the final draft recoverable if archival or publication fails.
        diag = pending.build_diagnostics(
            chapter_num, plan_json.get("chapter_title") or locked_title,
            len(full_chapter), plan_json, keeper_cache,
            scene_failures, final_scan, style_hits,
        )
        diag["reasons"]["chapter_review"] = chapter_reviews
        pending.save_pending(config, chapter_num, full_chapter, diag)
        _publish_chapter(config, chapter_num, full_chapter, plan_json,
                         keeper_cache, replacing=replacing,
                         locked_title=locked_title)
        checkpoint_file.unlink(missing_ok=True)
        return

    mode = getattr(config, "gate_fail_mode", "pending")
    if mode == "abort":
        failed_path = _save_failed_draft(
            config, chapter_num, "merged", full_chapter,
            {"stage": "final_scan", "scan_violations": final_scan.violations},
        )
        raise SceneQualityError(
            f"第 {chapter_num} 章合并正文未通过最终风格扫描，失败稿已保存: {failed_path}"
        )

    # pending 模式：草案 + 诊断落 revision/，不进 generated/ 与知识库，等作家定稿。
    diag = pending.build_diagnostics(
        chapter_num, plan_json.get("chapter_title") or locked_title,
        len(full_chapter), plan_json, keeper_cache,
        scene_failures, final_scan, style_hits,
    )
    diag["reasons"]["chapter_review"] = chapter_reviews
    pending.save_pending(config, chapter_num, full_chapter, diag)
    pf = config.cache_dir / "pipeline_progress.json"
    _atomic_write(
        pf, json.dumps({"last_completed_chapter": chapter_num,
                        "last_status": "pending"}, ensure_ascii=False),
    )
    print(f"第 {chapter_num} 章未通过全部质量闸门，已转入「待人工修订」队列"
          f"（revision/chapter_{chapter_num:02d}.md）")
    log.warning(f"第 {chapter_num} 章转入待人工修订队列: "
                f"{len(scene_failures)} 个场景失败, 最终扫描违规 "
                f"{len(final_scan.violations)} 条")
    return 2


def _publish_chapter(config, chapter_num: int, full_chapter: str, plan_json: dict,
                     keeper_cache: dict, *, replacing: bool, locked_title: str = ""):
    from engine.knowledge import transaction, ensure_seed, rebuild
    if replacing:
        rebuild(config, replacement=(chapter_num, full_chapter, plan_json))
    else:
        with transaction(config.bible_dir.parent):
            ensure_seed(config)
            _commit_chapter(config, chapter_num, full_chapter, plan_json, keeper_cache,
                            replacing=False, locked_title=locked_title)
    try:
        pending.remove_pending(config, chapter_num)
    except Exception as exc:
        log.warning("正文已发布，但待修订队列清理失败: %s", exc)


def _commit_chapter(config, chapter_num: int, full_chapter: str, plan_json: dict,
                    keeper_cache: dict, *, replacing: bool, locked_title: str = ""):
    """把一章正式定稿：读者信号 → 知识归档硬闸门 → 故事状态/缓存/DB 记账 → 原子发布。

    generate 与 publish N 共用。风格扫描结果走 keeper_cache["_style_hits"] 缓存，
    不再重扫，避免重复计费与测试里 scanner patch 副作用。
    """
    from engine.agents.reader_proxy import ReaderProxy
    from engine.agents.archivist import ArchivistAgent
    from engine.agents.story_keeper import StoryKeeperAgent
    from engine.agents.keeper import KeeperAgent

    reader = ReaderProxy()
    archivist = ArchivistAgent()
    story_keeper = StoryKeeperAgent()
    keeper = KeeperAgent()

    # 发布前完成所有外部审阅；任何异常都不会暴露 staging 正文。
    reader_result = keeper_cache.get("_reader_result") or reader.read(full_chapter)
    if reader_result.get("confusion_points"):
        log.warning(f"读者困惑点: {len(reader_result['confusion_points'])} 处")
    if reader_result.get("fatigue_points"):
        log.warning(f"读者疲劳点: {len(reader_result['fatigue_points'])} 处")
    print(f"  读者评分: {reader_result.get('overall_score', '?')}/10 | "
          f"续读意愿: {'是' if reader_result.get('would_continue') else '否'}")

    word_count = len(full_chapter)

    if not archivist.update_bible(chapter_num, plan_json, keeper_cache, full_chapter):
        raise RuntimeError(f"第 {chapter_num} 章知识归档失败，正文未发布")

    # 故事状态对账：提取失败时回滚发布，避免正文和知识脱节。
    story_keeper.update_state(config.bible_dir, chapter_num, plan_json, keeper_cache, full_chapter)

    # 章节级大纲追认（非致命）：实际写出的摘要写进 actual_timeline.md，planner 以实际为准
    try:
        from engine.agents.story_keeper import record_actual_events
        entry = record_actual_events(config, chapter_num, plan_json, keeper_cache)
        if entry:
            log.info(f"实际轨迹已记录: {entry[:60]}...")
    except Exception as e:
        log.warning(f"实际轨迹记录失败: {e}")

    keeper.save_cache(chapter_num, keeper_cache)
    _atomic_write(config.cache_dir / f"archive_plan_{chapter_num:02d}.json",
                  json.dumps(plan_json, ensure_ascii=False, indent=2))

    # DB 记账：章节成绩
    from engine.db import NovelDB
    style_hits = keeper_cache.get("_style_hits", [])
    try:
        _db = NovelDB(get_novel_dir())
        hard_cats = ("禁用词", "句式", "排版")
        hard = sum(r[3] for r in style_hits if r[1] in hard_cats)
        score = reader_result.get("overall_score")
        _db.log_chapter(chapter_num,
                        title=plan_json.get("chapter_title") or locked_title,
                        words=word_count,
                        reader_score=float(score) if score not in (None, "?", "") else None,
                        would_continue=reader_result.get("would_continue"),
                        violations=hard)
        for p in (reader_result.get("ai_suspect_points") or [])[:5]:
            _db.add_lesson(chapter_num, f"读者指认AI味: {str(p)[:60]}", "待下章写作时规避", "reader_ai_suspect")
        _db.close()
    except Exception as e:
        log.warning(f"DB 章节记账失败: {e}")

    if replacing:
        stale_db = NovelDB(get_novel_dir())
        try:
            stale_db.invalidate_from(chapter_num + 1)
        finally:
            stale_db.close()
        keeper.invalidate_from(chapter_num + 1)

    # 最后一步才原子发布正文；归档或审阅失败不会改动正式章节。
    archivist.save_chapter(chapter_num, full_chapter)
    pf = config.cache_dir / "pipeline_progress.json"
    _atomic_write(
        pf, json.dumps({"last_completed_chapter": chapter_num}, ensure_ascii=False),
    )

    print(f"第 {chapter_num} 章 完成  |  {word_count:,} 字")
    log.info(f"=== 第 {chapter_num} 章 完成 ===")

    # 打印本章伏笔操作
    ops = plan_json.get("clue_operations", [])
    if ops:
        print("本章伏笔操作:")
        for op in ops:
            print(f"  [{op.get('action','')}] {op.get('clue_id','')}: {op.get('method','')}")


def _revision_bible(config, chapter_num: int, source_text: str) -> dict:
    """Load only canon that was available to the chapter being revised."""
    bible = {}
    master = config.bible_dir / "master_bible.md"
    if master.exists():
        bible["master_bible"] = master.read_text(encoding="utf-8")

    foundations = config.bible_dir / "character_foundations.json"
    characters_path = foundations if foundations.exists() else config.bible_dir / "characters.json"
    characters = {"characters": {}}
    if characters_path.exists():
        raw = json.loads(characters_path.read_text(encoding="utf-8"))
        profiles = raw.get("characters", {}) if isinstance(raw, dict) else {}
        selected = {}
        for name, profile in profiles.items():
            if not isinstance(profile, dict):
                continue
            first = profile.get("first_appearance_chapter")
            if isinstance(first, int) and first > chapter_num:
                continue
            if name in source_text:
                selected[name] = profile
        characters["characters"] = selected
    bible["characters"] = characters

    clue_path = config.bible_dir / "clues.json"
    clues = {"clues": {}, "active_foreshadowing": {}}
    if clue_path.exists():
        raw = json.loads(clue_path.read_text(encoding="utf-8"))
        for key in clues:
            for clue_id, item in (raw.get(key, {}) or {}).items():
                if clue_id in source_text:
                    clues[key][clue_id] = item
    bible["clues"] = clues
    bible["motif_bank"] = {"motifs": []}
    return bible


def _build_revision_context(config, chapter_num: int, plan: dict,
                            original: str, feedback: str) -> dict:
    """Build chronological context for an old chapter without replanning it."""
    from engine.agents.researcher import ResearcherAgent
    from engine.agents.story_keeper import load_bare_state, writer_warnings

    source_text = original + "\n" + feedback + "\n" + json.dumps(plan, ensure_ascii=False)
    bible = _revision_bible(config, chapter_num, source_text)
    context = ResearcherAgent().run(plan, chapter_num, bible)
    context["_plan"] = plan

    previous = config.generated_dir / f"chapter_{chapter_num - 1:02d}.md"
    if previous.exists():
        context["previous_chapter_tail"] = previous.read_text(encoding="utf-8")[-1600:]
    following = config.generated_dir / f"chapter_{chapter_num + 1:02d}.md"
    if following.exists():
        context["next_chapter_head"] = following.read_text(encoding="utf-8")[:1600]

    state = load_bare_state(config.bible_dir)
    context["_story_state"] = state
    context["story_continuity_warnings"] = writer_warnings(
        state, chapter_num, dict(plan, draft=original),
    )
    return context


def cmd_revise(chapter_num: int, feedback: str):
    """修订已生成章节，并跑与新章一致的整章质量闸门。"""
    config = get_config()
    cf = config.generated_dir / f"chapter_{chapter_num:02d}.md"
    if not cf.exists():
        raise CommandError(f"第 {chapter_num} 章尚未生成，无法修订")

    original = cf.read_text(encoding="utf-8")
    print(f"修订第 {chapter_num} 章: {feedback}")

    from engine.agents.writer import WriterAgent
    from engine.agents.reviewers import ReviewerAgent
    from engine.agents.reader_proxy import ReaderProxy
    from engine.agents.dialogue_auditor import DialogueAuditor
    from engine.prompts_loader import get_prompt
    writer = WriterAgent()

    plan_file = config.cache_dir / f"archive_plan_{chapter_num:02d}.json"
    plan = json.loads(plan_file.read_text(encoding="utf-8")) if plan_file.exists() else {}
    context_pack = _build_revision_context(config, chapter_num, plan, original, feedback)
    review_context = {
        "plan": plan,
        "previous_chapter_tail": context_pack.get("previous_chapter_tail", ""),
        "next_chapter_head": context_pack.get("next_chapter_head", ""),
        "characters": context_pack.get("relevant_characters", {}),
        "memory_notes": context_pack.get("memory_notes", ""),
        "story_continuity_warnings": context_pack.get("story_continuity_warnings", ""),
        "recent_chapters_summary": context_pack.get("recent_chapters_summary", ""),
    }

    # 取 writer prompt 中的写作规则部分，确保修订时规则不丢失
    writer_system, _ = get_prompt("writer")
    rule_section = writer_system.split("特殊条件")[0] if "特殊条件" in writer_system else writer_system[:800]

    prompt = (
        f"{rule_section}\n\n"
        f"【任务】根据用户要求修订章节正文。保持人物性格、剧情走向不变。\n\n"
        f"【修改要求】\n{feedback}\n\n"
        f"【连续性上下文】\n{json.dumps(review_context, ensure_ascii=False, indent=2)}\n\n"
        f"【执行要求】\n"
        f"- 只改与修改要求相关的部分，其余保留原文\n"
        f"- 遵守本书格式；普通词语按语境判断，不为避词损害意思\n"
        f"- 对话符合人物利益与声口，不强加口癖、废话或打断\n"
        f"- 下一章片段只用于避免矛盾，不得把后续事件提前写进本章\n"
        f"- 不凭空加入后续经历、能力或关系，不重复已经完成的动作\n\n"
        f"【原文】\n{original}\n\n"
        f"输出修订后的完整正文，不要任何说明或标注。"
    )
    revised = writer._call_llm(prompt, 0)
    from engine.quality import edit_chapter
    revised, scan, reader_result, chapter_reviews, chapter_passed = edit_chapter(
        revised, plan, chapter_num, context_pack, config, writer,
        ReviewerAgent(), ReaderProxy(), DialogueAuditor(),
    )
    diag = pending.build_diagnostics(chapter_num, plan.get("chapter_title", ""), len(revised),
                                     plan, {}, [], scan, scan.to_rows(chapter_num))
    diag["revision_request"] = feedback
    diag["quality_passed"] = bool(chapter_passed and scan.passed)
    diag["reader_result"] = reader_result
    diag["reasons"]["chapter_review"] = chapter_reviews
    pending.save_pending(config, chapter_num, revised, diag)
    quality = "已通过完整质量闸门" if diag["quality_passed"] else "仍需人工修订"
    print(f"第 {chapter_num} 章修订稿已进入待修订队列（{quality}），原定稿未覆盖。")
    return 2


def cmd_pending():
    """列出待人工修订队列（未通过全部质量闸门的章节）。"""
    config = get_config()
    items = pending.list_pending(config)
    if not items:
        print("待修订队列为空")
        return
    print(f"待人工修订 {len(items)} 章:")
    for item in items:
        reasons = item.get("reasons") or {}
        scenes = len(reasons.get("scene_failures") or [])
        final_scan = len(reasons.get("final_scan") or [])
        detail = ""
        if scenes or final_scan:
            detail = f"（场景失败 {scenes} 个, 最终扫描 {final_scan} 条）"
        print(f"  第 {item['num']} 章: {item.get('title') or '(未命名)'} | "
              f"{item.get('words', 0):,} 字 | {item.get('created_at', '')}{detail}")
    print(f"\n定稿: python novel.py --novel {get_novel()} publish <章号>")
    print(f"丢弃: python novel.py --novel {get_novel()} discard <章号>")


def cmd_publish(chapter_num: int):
    """把待修订队列中的一章正式定稿：跑完整归档管线，正文进 generated/ 与知识库。"""
    config = get_config()
    entry = pending.load_pending(config, chapter_num)
    if entry is None:
        raise CommandError(f"第 {chapter_num} 章不在待修订队列")
    content = entry["content"]
    if not content.strip():
        raise CommandError("正文为空，不能发布")
    from engine.knowledge import check_ready
    try:
        check_ready(config, chapter_num, publishing=True)
    except ValueError as exc:
        raise CommandError(str(exc)) from exc
    diag = entry["diagnostics"] or {}
    plan_json = diag.get("plan_json") or {}
    if not plan_json.get("scene_outline"):
        plan_json["scene_outline"] = [{
            "scene_id": 1, "type": "high_conflict",
            "target_emotion": 0.8, "description": "待修订章节",
        }]

    from engine.agents.keeper import KeeperAgent
    from engine.style_kit import scanner
    keeper = KeeperAgent()
    keeper_cache = keeper.reconcile_final_chapter(keeper.init_cache(chapter_num), content, chapter_num)
    keeper_cache["_style_hits"] = scanner.scan(content).to_rows(chapter_num)
    title = diag.get("title") or plan_json.get("chapter_title") or ""
    replacing = (config.generated_dir / f"chapter_{chapter_num:02d}.md").exists()
    _publish_chapter(config, chapter_num, content, plan_json, keeper_cache,
                     replacing=replacing, locked_title=title)
    print(f"第 {chapter_num} 章已发布（来源：待人工修订队列）")


def cmd_discard(chapter_num: int):
    """丢弃待修订队列中的一章（不发布、不入知识库）。"""
    config = get_config()
    if not pending.remove_pending(config, chapter_num):
        raise CommandError(f"第 {chapter_num} 章不在待修订队列")
    print(f"第 {chapter_num} 章待修订稿已丢弃")


def cmd_summary(volume_num: int, prompt: str = ""):
    """生成/修订卷末总结"""
    config = get_config()
    # 找到对应卷
    vol_key = f"volume_{volume_num}"
    vol = config.volume_config.get(vol_key)
    if not vol:
        raise CommandError(f"未找到第 {volume_num} 卷")
    lo, hi = vol["chapters"]

    gen_dir = config.generated_dir
    summaries = []
    from engine.db import NovelDB
    db = NovelDB(get_novel_dir())
    try:
        rows = db.conn.execute(
            "SELECT chapter,summary FROM chapter_summaries "
            "WHERE chapter BETWEEN ? AND ? ORDER BY chapter", (lo, hi)
        ).fetchall()
    finally:
        db.close()
    summaries = [f"第{row['chapter']}章: {row['summary']}" for row in rows]
    if not summaries:
        for cf in chapter_files(gen_dir, first_chapter=lo, last_chapter=hi):
            ch = parse_chapter_number(cf)
            text = cf.read_text(encoding="utf-8")
            first_line = text.strip().split("\n")[0] if text else cf.stem
            summaries.append(f"第{ch}章: {first_line}")

    if not summaries:
        raise CommandError(f"第{volume_num}卷尚未生成任何章节")

    from engine.prompts_loader import get_prompt
    system, _ = get_prompt("volume_summary")
    system = system.format(
        volume_name=vol["name"],
        vol_start=lo, vol_end=hi,
        chapter_summaries="\n\n".join(summaries),
        volume_emotion=vol["core_emotion"],
    )

    # 如果是修订模式
    summary_file = gen_dir / f"volume_{volume_num}_summary.md"
    if "--revise" in sys.argv or "-r" in sys.argv or prompt:
        if not summary_file.exists():
            raise CommandError(
                "卷末总结尚未生成，请先生成: python novel.py --novel {} summary {}".format(
                    get_novel(), volume_num)
            )
        original = summary_file.read_text(encoding="utf-8")
        system += f"\n\n【修改要求】{prompt}\n【原文】\n{original}"
        print(f"修订第{volume_num}卷总结: {prompt}")

    from engine.llm_client import chat
    from engine.agents.writer import WriterAgent
    writer = WriterAgent()
    print(f"生成第{volume_num}卷总结 ({vol['name']})...")
    text = chat(config.writer_model, user_prompt=system)
    summary_file.write_text(text, encoding="utf-8")
    print(f"卷末总结已保存: {summary_file}")

    # 写作→规划闭环：产出修订建议，供下一卷规划遵循（非致命）
    try:
        from engine.agents.story_keeper import append_volume_revisions
        block = append_volume_revisions(config, volume_num, text)
        if block:
            print(f"卷修订建议已写入 bible/volume_revisions.md（供第{volume_num + 1}卷规划）")
    except Exception as e:
        log.warning(f"卷修订建议生成失败: {e}")


# ============================================================
# 主入口
# ============================================================

def _main():
    args = _parse_args()
    cmd = args["command"]
    novel = args["novel"]

    if cmd == "list":
        return cmd_list()

    if cmd == "create":
        return cmd_create(args)

    if not novel:
        raise CommandError("请先创建小说，或使用 --novel <id> 指定小说")

    # 需要设置小说的命令
    set_novel(novel)
    from engine.locking import novel_lock
    from engine.usage import usage_run, task_limit
    with novel_lock(get_novel_dir()), usage_run(
            get_novel_dir(), cmd, task_limit(get_config(), cmd)):
        return _dispatch(args)


def _dispatch(args):
    cmd, novel = args["command"], args["novel"]

    if cmd == "scan":
        return cmd_scan(args["chapter"])

    if cmd == "db":
        return cmd_db(args.get("db_sub", "stats"))

    if cmd == "status":
        return cmd_status()

    if cmd == "outline":
        return cmd_outline(args["prompt"], args["force"])

    if cmd == "titles":
        return cmd_titles(args["prompt"])

    if cmd == "view":
        return cmd_view(args)

    if cmd == "generate":
        return cmd_generate(args["chapter"], args["prompt"], args["overwrite"],
                            args["outline_override"])

    if cmd == "revise":
        feedback = args["content"] or args["prompt"]
        if not feedback:
            raise CommandError(
                "请提供修改要求: python novel.py --novel {} revise <章号> <修改要求>".format(novel)
            )
        return cmd_revise(args["chapter"], feedback)

    if cmd == "pending":
        return cmd_pending()

    if cmd == "rebuild":
        from engine.knowledge import rebuild
        print(f"已从定稿正文重建 {rebuild(get_config())} 章知识；旧知识备份保留在 .history")
        return

    if cmd == "prepare":
        from engine.foundation import prepare
        print(f"已补全 {prepare(get_config())} 位人物的动机、边界与声口")
        return

    if cmd == "recover":
        from engine.knowledge import recover
        print("已恢复中断前的知识与正文" if recover(get_novel_dir()) else "没有中断的归档事务")
        return

    if cmd == "publish":
        return cmd_publish(args["chapter"])

    if cmd == "discard":
        return cmd_discard(args["chapter"])

    if cmd == "summary":
        return cmd_summary(args["volume"], args["prompt"])

    if cmd == "promo":
        return cmd_promo(args)

    # 没有命令时显示帮助
    print("小说创作引擎 — 命令列表\n")
    print("  python novel.py create --id <slug> --title <书名> [--chapters N] [--words N] [--genre 类型] [--description 简介]")
    print()
    print("  配置与规划:")
    print("    python novel.py --novel <名> outline         生成全书大纲 → bible/outline.md")
    print("    python novel.py --novel <名> titles          根据大纲生成章名 → bible/chapter_titles.json")
    print("    python novel.py --novel <名> titles -p \"要求\" 重新生成章名")
    print()
    print("  写作:")
    print("    python novel.py --novel <名> generate <章号>       生成指定章节")
    print("    python novel.py --novel <名> generate <章号> -p \"指令\" 带创作指令")
    print("    python novel.py --novel <名> revise <章号> <修改要求>  修订章节")
    print("    python novel.py --novel <名> pending            列出待人工修订队列")
    print("    python novel.py --novel <名> rebuild            从定稿正文重建全部知识")
    print("    python novel.py --novel <名> recover            恢复中断的归档事务")
    print("    python novel.py --novel <名> publish <章号>     待修订章节定稿发布")
    print("    python novel.py --novel <名> discard <章号>     丢弃待修订章节")
    print()
    print("  收尾:")
    print("    python novel.py --novel <名> summary <卷号>        生成卷末总结")
    print("    python novel.py --novel <名> summary <卷号> -r \"要求\" 修订卷末总结")
    print()
    print("  查看:")
    print("    python novel.py --novel <名> view outline     查看全书大纲")
    print("    python novel.py --novel <名> view titles      查看全部章名")
    print("    python novel.py --novel <名> view chapter N   查看第N章正文")
    print("    python novel.py --novel <名> view bible       查看知识库状态")
    print("    python novel.py --list                        列出所有小说")
    print("    python novel.py --novel <名> status           查看创作进度")
    print()
    return 0


def main():
    from engine.locking import NovelBusyError
    from engine.usage import CallBudgetExceeded
    try:
        result = _main()
        return result if isinstance(result, int) else 0
    except (CommandError, SceneQualityError, NovelBusyError, CallBudgetExceeded) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
