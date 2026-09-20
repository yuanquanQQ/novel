"""Install the reviewed opening and authored, source-bound knowledge without API calls."""
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import pending, settings
from engine.chapter_files import chapter_files, parse_chapter_number
from engine.knowledge import content_hash, rebuild, transaction
from engine.novel_creator import _prompts
from engine.quality import word_count
from engine.style_kit.scanner import scan


def main():
    settings.set_novel("xinghai-zhumingshi")
    cfg = settings.get_config()
    root = settings.get_novel_dir()
    stage = ROOT / "revisions" / "xinghai-opening"
    marker = cfg.bible_dir / "opening_revision_v2.json"
    if marker.exists():
        raise SystemExit("Opening migration already installed; refusing to overwrite later edits.")
    if pending.list_pending(cfg):
        raise SystemExit("Pending manuscripts exist; resolve them before migration.")
    for path in (ROOT / "runtime" / "tasks").glob("*.json"):
        task = json.loads(path.read_text(encoding="utf-8"))
        if task.get("novel") == "xinghai-zhumingshi" and task.get("status") == "running":
            raise SystemExit("A writing task is running; stop it before migration.")
    if {parse_chapter_number(p) for p in chapter_files(cfg.generated_dir)} != {1, 2, 3}:
        raise SystemExit("Published chapter set changed; re-review required.")
    records = json.loads((stage / "opening_archive.json").read_text(encoding="utf-8"))
    texts = {n: (stage / f"chapter_{n:02d}.md").read_text(encoding="utf-8") for n in (1, 2, 3)}
    for n, text in texts.items():
        if not scan(text).passed or not 2250 <= word_count(text) <= 3750:
            raise ValueError(f"Chapter {n} failed preflight")
        records[str(n)]["source_hash"] = content_hash(text)
    with transaction(root) as backup:
        foundations = (stage / "character_foundations.json").read_text(encoding="utf-8")
        pending._atomic_write(cfg.bible_dir / "character_foundations.json", foundations)
        seed = {"characters": json.loads(foundations), "clues": {"clues": {}, "active_foreshadowing": {}}}
        pending._atomic_write(cfg.bible_dir / "knowledge_seed.json", json.dumps(seed, ensure_ascii=False, indent=2))
        for n, text in texts.items():
            pending._atomic_write(cfg.generated_dir / f"chapter_{n:02d}.md", text)

        master_file = cfg.bible_dir / "master_bible.md"
        master = master_file.read_text(encoding="utf-8")
        master = master.replace("全篇分四卷：", "全篇分四个叙事阶段（与每60章的技术分卷区分）：")
        for old, new in (("卷一零号", "阶段一零号"), ("卷二裂隙", "阶段二裂隙"),
                         ("卷三神代", "阶段三神代"), ("卷四万星", "阶段四万星")):
            master = master.replace(old, new)
        master += ("\n## 开篇创作约定\n"
                   "沈渊从业七年，来到零号废墟一个月；印记在左掌。人物固定设定见 character_foundations.json。\n"
                   "前期阅读期待为资源回收、工程解题和自主生存；每章有主动决策和可见结果，悬疑不能抵消全部收益。\n"
                   "能力受材料、能量、体力与工艺约束，不凭空造物，不无限抵抗电击。\n"
                   "单章目标约3000字，可按剧情浮动；避免用重复感官和无关道具延长篇幅。\n")
        pending._atomic_write(master_file, master)

        outline_lines = {
            1: "- **第1章 废铁场**：沈渊为保住结算清理车道，废船异常冷却管泄漏引发塌方，左掌接触方碑获得星环；他消解污染卡箍脱困，配合吊装完成清场，拿到八十信用点，并发现污染残渣能转为晶砂。*功能：明确工程师目标与能力边界，首章给出实际收益并引向废反应芯；伏笔：引入 F001*",
            2: "- **第2章 第一颗星核**：沈渊按民用清单登记最小碎芯，在屏蔽柜内分次提炼星核，点亮旧炉、驱动绞盘完成清场；他挣到一百二十并首付三百买下工具舱。炉内银线和叹息引出未知，穆辛改动货物分类后上门，沈渊已留单据备份。*功能：兑现污染物变能源的回收翻盘，落实产权与成本，铺好官面冲突的证据；伏笔：引入 F002*",
            3: "- **第3章 巡检官**：穆辛封存工具舱并带走沈渊，借电击索取处理方法；沈渊借受激电极与旧椅结构使椅子结晶挣脱，凭货单备份和技术价值取回星核与自由，解除封存并争取老韩医费。他直接去废弃信标站另找落脚点；穆辛以泰坦特批权限登记S级，得到保持活动、记录能源节点的命令。*功能：主角主动反制，确立独立基地需求；将官面威胁升级为秘密观测，衔接两位流浪者；伏笔：引入 F003*",
        }
        for path in (cfg.bible_dir / "outline.md", cfg.bible_dir / "outline_parts" / "volume_1" / "section_1_10.md"):
            if not path.exists():
                continue
            lines = path.read_text(encoding="utf-8").splitlines()
            for i, line in enumerate(lines):
                match = re.match(r"^- \*\*第([123])章 ", line)
                if match:
                    lines[i] = outline_lines[int(match.group(1))]
            pending._atomic_write(path, "\n".join(lines) + "\n")

        prompts_path = root / "novel_prompts.json"
        prompts = json.loads(prompts_path.read_text(encoding="utf-8"))
        meta = prompts["_meta"]
        fresh = _prompts(meta["novel"], meta.get("genre", ""), master)
        for key in ("planner", "writer", "reviewer_immediate", "reviewer_heavy", "dialogue_auditor",
                    "keeper", "archivist", "story_keeper", "story_check", "reader_proxy", "chapter_editor", "foundation"):
            prompts[key] = fresh[key]
        prompts["_meta"] = dict(meta, version="2.0", description=master)
        pending._atomic_write(prompts_path, json.dumps(prompts, ensure_ascii=False, indent=2))
        config_path = root / "config.py"
        config_text = config_path.read_text(encoding="utf-8")
        config_text, changed = re.subn(r"words_per_chapter: int = \d+", "words_per_chapter: int = 3000", config_text)
        if changed != 1:
            raise ValueError("Unexpected config format")
        if "chapter_edit_max_retries:" not in config_text:
            config_text = config_text.replace("    heavy_review_interval:", "    chapter_edit_max_retries: int = 1\n    heavy_review_interval:")
        pending._atomic_write(config_path, config_text)
        from engine.prompts_loader import reload
        reload()
        rebuild(cfg, records=records, _in_transaction=True)
        pending._atomic_write(marker, json.dumps({"version": 2, "backup": str(backup),
            "source_hashes": {n: content_hash(text) for n, text in texts.items()},
            "word_counts": {n: word_count(text) for n, text in texts.items()},
            "archive_source": "author-reviewed, no external model calls"}, ensure_ascii=False, indent=2))
    print(json.dumps({"backup": str(backup), "chapters": 3, "words": [word_count(texts[n]) for n in (1, 2, 3)]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
