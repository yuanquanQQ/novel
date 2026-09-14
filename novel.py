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
import logging
import re
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_ROOT))

from engine.settings import set_novel, get_novel, get_novel_dir, get_config, NOVELS_DIR

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
        elif a in ("outline", "titles", "status"):
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
        i += 1
    return parsed


# ============================================================
# 命令实现
# ============================================================

def cmd_create(args):
    """创建独立的新小说工作区。"""
    from engine.novel_creator import create_novel
    path = create_novel(
        args["id"], args["title"], args["chapter_count"],
        args["words_per_chapter"], args["genre"], args["description"])
    print(f"小说已创建: {path}")


def cmd_list():
    """列出所有可用小说"""
    print("可用小说:")
    for d in sorted(NOVELS_DIR.iterdir()):
        if d.is_dir():
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

    existing = sorted(gen_dir.glob("chapter_*.md")) if gen_dir.exists() else []
    total_words = sum(len(f.read_text(encoding="utf-8")) for f in existing)
    vols = {}
    for f in existing:
        ch_num = int(f.stem.split("_")[1])
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
        pending = sum(1 for f in active.values() if f.get("status") == "pending")
        resolved = sum(1 for f in active.values() if f.get("status") == "resolved")
        print(f"\n伏笔: {resolved} 已回收 / {pending} 待回收 / {len(active)} 总计")


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
    for cf in sorted(gen_dir.glob("chapter_*.md"))[-10:]:
        if cf.exists():
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
        existing = list(gen_dir.glob("chapter_*.md"))
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


def cmd_outline(prompt=""):
    """分卷生成全书大纲 → bible/outline.md"""
    config = get_config()

    bible = {}
    for fn in ["master_bible.md", "characters.json", "clues.json", "motif_bank.json"]:
        fp = config.bible_dir / fn
        if fp.exists():
            if fp.suffix == ".json":
                bible[fp.stem] = json.loads(fp.read_text(encoding="utf-8"))
            else:
                bible[fp.stem] = fp.read_text(encoding="utf-8")

    from engine.llm_client import chat

    all_parts = []
    vols = list(config.volume_config.items())

    for vk, v in vols:
        lo, hi = v["chapters"]
        print(f"生成 {v['name']} (第{lo}-{hi}章) ...")

        vol_prompt = (
            f"你是资深小说策划编辑。请为《{config.story_title}》{v['name']}生成详细大纲。\n\n"
            f"【世界观】{bible.get('master_bible','')[:2500]}\n\n"
            f"【本卷】{v['name']}(第{lo}-{hi}章) | 情绪:{v['core_emotion']} | 重点:{v['focus']}\n\n"
            f"【人物】{json.dumps(bible.get('characters',{}), ensure_ascii=False, indent=2)[:2000]}\n\n"
            f"【线索池】{json.dumps({k:v.get('name','') for k,v in bible.get('clues',{}).get('clues',{}).items()}, ensure_ascii=False)}\n"
            f"【伏笔池】{json.dumps({k:v.get('name','') for k,v in bible.get('clues',{}).get('active_foreshadowing',{}).items()}, ensure_ascii=False)}\n\n"
            f"【强制格式】\n"
            f"开头先写一段卷总结要100-150字。\n\n"
            f"然后分小节列大纲，必须输出第{lo}到第{hi}章全部{hi-lo+1}章，一章不能少！\n"
            f"输出完毕后请自查：是否恰好{hi-lo+1}行？缺了任何一章都是失败的。\n\n"
            f"每行格式：\n"
            f"- **第N章 章名**：核心剧情（10-30字）。*功能 / 引入/回收*\n\n"
            f"章名2-6字精炼。功能必填。最后第{hi}章是卷末收束章。\n"
            f"按故事弧线分小节（每8-12章），小节标题 ### 第N-M章：小节名"
        )
        if prompt:
            vol_prompt += f"\n【用户要求】{prompt}\n"

        part = chat(config.planner_model, user_prompt=vol_prompt)
        all_parts.append(f"## {v['name']} (第{lo}-{hi}章)\n{v['focus']}\n{part}")

    outline = f"# {config.story_title} — 全书大纲\n\n" + "\n\n".join(all_parts)
    outline_file = config.bible_dir / "outline.md"
    outline_file.write_text(outline, encoding="utf-8")
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
        print("错误: 未找到 bible/outline.md，请先运行: python novel.py --novel {} outline".format(get_novel()))
        return

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
        print("未能提取章名。试试: python novel.py --novel {} titles -p '要求'".format(get_novel()))
        return

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


def cmd_generate(chapter_num: int, instruction: str = ""):
    """生成单章"""
    from engine.agents.planner import PlannerAgent
    from engine.agents.researcher import ResearcherAgent
    from engine.agents.writer import WriterAgent
    from engine.agents.reviewers import ReviewerAgent
    from engine.agents.keeper import KeeperAgent
    from engine.agents.archivist import ArchivistAgent
    from engine.agents.dialogue_auditor import DialogueAuditor
    from engine.agents.foreshadowing_steward import ForeshadowingSteward
    from engine.agents.reader_proxy import ReaderProxy

    config = get_config()
    planner = PlannerAgent()
    researcher = ResearcherAgent()
    writer = WriterAgent()
    reviewers = ReviewerAgent()
    keeper = KeeperAgent()
    archivist = ArchivistAgent()
    auditor = DialogueAuditor()
    steward = ForeshadowingSteward()
    reader = ReaderProxy()

    for d in [config.bible_dir, config.generated_dir, config.cache_dir]:
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

    plan_json = planner.run(chapter_num, instruction or f"继续推进第{chapter_num}章剧情", bible, lessons, locked_title)
    log.info(f"大纲: {plan_json.get('chapter_title','')} ({len(plan_json.get('scene_outline',[]))} 场景)")

    # 伏笔管家审计大纲
    steward_result = steward.audit(plan_json, chapter_num, bible)
    if steward_result.get("operation_warnings"):
        log.warning(f"伏笔管家警告: {steward_result['operation_warnings']}")
    if steward_result.get("overdue"):
        print(f"  [伏笔管家] 过期伏笔: {steward_result['overdue']}")

    context_pack = researcher.run(plan_json, chapter_num, bible)
    context_pack["_plan"] = plan_json

    keeper_cache = keeper.init_cache(chapter_num)

    from engine.style_kit import scanner
    style_hits = []
    feedback_map = {}
    for scene in plan_json.get("scene_outline", []):
        sid = scene.get("scene_id", "?")
        fail = 0
        max_fail = config.immediate_review_max_retries
        while True:
            fb = feedback_map.get(sid, "")
            draft = writer.run(scene, keeper_cache, context_pack, chapter_num, fb)

            # 第一道：确定性扫描（零成本、必命中，禁用词/句式/排版）
            scan_result = scanner.scan(draft)
            style_hits.extend(scan_result.to_rows(chapter_num))
            if not scan_result.passed and fail < max_fail:
                fail += 1
                feedback_map[sid] = scan_result.to_suggestions()
                log.warning(f"  场景 {sid} 机械扫描拦截 {len(scan_result.violations)} 条")
                continue

            # 第二道：LLM 语义审阅
            review = reviewers.immediate_check(draft, scene, keeper_cache, context_pack)
            if not review.get("passed", False) and fail < max_fail:
                fail += 1
                feedback_map[sid] = review.get("suggestions", "")
                continue

            # 第三道：对话声纹审计
            audit = auditor.audit(draft, context_pack)
            if not audit.get("passed", False) and fail < max_fail:
                fail += 1
                feedback_map[sid] = audit.get("suggestions", "")
                log.warning(f"  场景 {sid} 声纹违规: {audit.get('suggestions','')}")
                continue

            if fail >= max_fail:
                draft = "[系统提示：场景生成失败，启用骨架降级]\n" + draft
            keeper_cache = keeper.update(keeper_cache, draft, chapter_num, sid)
            break
    keeper_cache["_style_hits"] = style_hits
    if style_hits:
        print(f"  [风格扫描] 本章命中风格问题 {len(style_hits)} 条")

    all_scenes = keeper_cache.get("all_scenes", [])
    full_chapter = writer.merge_scenes(all_scenes, plan_json, chapter_num)

    if chapter_num % config.heavy_review_interval == 0:
        heavy = reviewers.heavy_check(full_chapter, plan_json, chapter_num)
        if heavy.get("patch_instructions"):
            log.warning(f"重型审查: {heavy.get('score','?')}分, {len(heavy['patch_instructions'])} 条指示")
            patched = writer.apply_patches(full_chapter, plan_json, heavy["patch_instructions"], chapter_num)
            before, re_scan = scanner.scan(full_chapter), scanner.scan(patched)
            if re_scan.passed or len(re_scan.violations) < len(before.violations):
                full_chapter = patched
                style_hits.extend(re_scan.to_rows(chapter_num))
            else:
                log.warning("补丁后扫描更差，保留原稿")
    else:
        heavy = {"score": None, "patch_instructions": []}
    keeper_cache["_style_hits"] = style_hits

    archivist.save_chapter(chapter_num, full_chapter)
    archivist.update_bible(chapter_num, plan_json, keeper_cache)
    keeper.save_cache(chapter_num, keeper_cache)

    # 读者代理人反馈
    reader_result = reader.read(full_chapter)
    if reader_result.get("confusion_points"):
        log.warning(f"读者困惑点: {len(reader_result['confusion_points'])} 处")
    if reader_result.get("fatigue_points"):
        log.warning(f"读者疲劳点: {len(reader_result['fatigue_points'])} 处")
    print(f"  读者评分: {reader_result.get('overall_score', '?')}/10 | "
          f"续读意愿: {'是' if reader_result.get('would_continue') else '否'}")

    word_count = len(full_chapter)

    # DB 记账：章节成绩
    from engine.db import NovelDB
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

    # 记录进度
    pf = config.cache_dir / "pipeline_progress.json"
    pf.write_text(json.dumps({"last_completed_chapter": chapter_num}, ensure_ascii=False), encoding="utf-8")

    print(f"第 {chapter_num} 章 完成  |  {word_count:,} 字")
    log.info(f"=== 第 {chapter_num} 章 完成 ===")

    # 打印本章伏笔操作
    ops = plan_json.get("clue_operations", [])
    if ops:
        print("本章伏笔操作:")
        for op in ops:
            print(f"  [{op.get('action','')}] {op.get('clue_id','')}: {op.get('method','')}")


def cmd_revise(chapter_num: int, feedback: str):
    """修订已生成章节"""
    config = get_config()
    cf = config.generated_dir / f"chapter_{chapter_num:02d}.md"
    if not cf.exists():
        print(f"错误: 第 {chapter_num} 章尚未生成")
        return

    original = cf.read_text(encoding="utf-8")
    print(f"修订第 {chapter_num} 章: {feedback}")

    from engine.agents.writer import WriterAgent
    from engine.prompts_loader import get_prompt
    writer = WriterAgent()

    # 取 writer prompt 中的写作规则部分，确保修订时规则不丢失
    writer_system, _ = get_prompt("writer")
    rule_section = writer_system.split("特殊条件")[0] if "特殊条件" in writer_system else writer_system[:800]

    prompt = (
        f"{rule_section}\n\n"
        f"【任务】根据用户要求修订章节正文。保持人物性格、剧情走向不变。\n\n"
        f"【修改要求】\n{feedback}\n\n"
        f"【执行要求】\n"
        f"- 只改与修改要求相关的部分，其余保留原文\n"
        f"- 修改后全文不能出现任何禁用词\n"
        f"- 对话依然要像真人说话：有打断、有废话、有口癖\n\n"
        f"【原文】\n{original}\n\n"
        f"输出修订后的完整正文，不要任何说明或标注。"
    )
    revised = writer._call_llm(prompt, 0)
    cf.write_text(revised, encoding="utf-8")

    # 记录教训（JSONL + SQLite 双写）+ 修订后复扫
    from engine.style_kit import scanner
    from engine.db import NovelDB
    lp = config.bible_dir / "lessons_learned.jsonl"
    entry = json.dumps({"chapter": chapter_num, "issue": feedback, "fix": "用户手动修订"}, ensure_ascii=False)
    with open(lp, "a", encoding="utf-8") as f:
        f.write(entry + "\n")
    try:
        _db = NovelDB(get_novel_dir())
        _db.add_lesson(chapter_num, feedback, "用户手动修订", "user")
        rows = scanner.scan(revised).to_rows(chapter_num)
        if rows:
            _db.add_style_hits(rows)
        _db.close()
    except Exception as e:
        log.warning(f"DB lesson 写入失败: {e}")
    post = scanner.scan(revised)
    if not post.passed:
        print(f"  ⚠ 修订稿仍含机械违规 {len(post.violations)} 条（已记入风格档案）")

    print(f"第 {chapter_num} 章已修订 | {len(revised):,} 字")


def cmd_summary(volume_num: int, prompt: str = ""):
    """生成/修订卷末总结"""
    config = get_config()
    # 找到对应卷
    vol_key = f"volume_{volume_num}"
    vol = config.volume_config.get(vol_key)
    if not vol:
        print(f"错误: 未找到第 {volume_num} 卷")
        return
    lo, hi = vol["chapters"]

    # 收集本章摘要
    gen_dir = config.generated_dir
    summaries = []
    for ch in range(lo, hi + 1):
        cf = gen_dir / f"chapter_{ch:02d}.md"
        if cf.exists():
            text = cf.read_text(encoding="utf-8")
            summaries.append(f"第{ch}章: {text[:200]}...")

    if not summaries:
        print(f"错误: 第{volume_num}卷尚未生成任何章节")
        return

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
            print("错误: 卷末总结尚未生成，请先生成: python novel.py --novel {} summary {}".format(get_novel(), volume_num))
            return
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


# ============================================================
# 主入口
# ============================================================

def main():
    args = _parse_args()
    cmd = args["command"]
    novel = args["novel"]

    if cmd == "list":
        return cmd_list()

    if cmd == "create":
        return cmd_create(args)

    if not novel:
        print("请先创建小说，或使用 --novel <id> 指定小说")
        return

    # 需要设置小说的命令
    set_novel(novel)

    if cmd == "scan":
        return cmd_scan(args["chapter"])

    if cmd == "db":
        return cmd_db(args.get("db_sub", "stats"))

    if cmd == "status":
        return cmd_status()

    if cmd == "outline":
        return cmd_outline(args["prompt"])

    if cmd == "titles":
        return cmd_titles(args["prompt"])

    if cmd == "view":
        return cmd_view(args)

    if cmd == "generate":
        return cmd_generate(args["chapter"], args["prompt"])

    if cmd == "revise":
        feedback = args["content"] or args["prompt"]
        if not feedback:
            print("请提供修改要求: python novel.py --novel {} revise <章号> <修改要求>".format(novel))
            return
        return cmd_revise(args["chapter"], feedback)

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

if __name__ == "__main__":
    main()