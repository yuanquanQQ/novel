# Style Kit — 确定性 AI 痕迹扫描器（纯代码，零 LLM 成本）
# 用法: python -m engine.style_kit.scanner 某草稿.txt

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

RULES_FILE = Path(__file__).resolve().parent / "banned_words.json"


def load_rules(path: Path = None) -> dict:
    return json.loads((path or RULES_FILE).read_text(encoding="utf-8"))


@dataclass
class ScanResult:
    violations: list = field(default_factory=list)   # hard 级：必须打回
    warnings: list = field(default_factory=list)     # soft 级：提示
    metrics: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.violations

    def to_suggestions(self) -> str:
        parts = []
        for v in self.violations:
            parts.append(
                f"清除「{v['pattern']}」({v['count']}处: {v['where']})"
                + (f"，{v['hint']}" if v.get("hint") else "")
            )
        for w in self.warnings:
            parts.append(
                f"减少「{w['pattern']}」({w['count']}处)，{w.get('hint', '')}"
            )
        return "；".join(parts)

    def to_rows(self, chapter: int) -> list:
        rows = []
        for item in self.violations + self.warnings:
            rows.append((chapter, item["category"], item["pattern"],
                         item["count"]))
        return rows


def _locations(paragraphs: list, word: str, cap: int = 3) -> str:
    hits = [i + 1 for i, p in enumerate(paragraphs) if word in p]
    s = ",".join(f"第{n}段" for n in hits[:cap])
    return s + ("…" if len(hits) > cap else "")


def _dialogue_ratio(text: str) -> float:
    body = re.sub(r"\s", "", text)
    if not body:
        return 0.0
    quoted = re.findall(r"「[^」]*」|“[^”]*”|\"[^\"]*\"", text)
    qchars = sum(len(re.sub(r"\s", "", q)) for q in quoted)
    return round(qchars / len(body), 3)


def _split_sentences(text: str) -> list:
    return [s.strip() for s in re.split(r"[。！？…]+", text) if s.strip()]


def scan(text: str, rules: dict = None) -> ScanResult:
    rules = rules or load_rules()
    res = ScanResult()
    paragraphs = [p for p in re.split(r"\n+", text) if p.strip()]
    m = rules.get("metrics", {})

    for w in rules.get("hard_words", []):
        c = text.count(w)
        if c:
            target = res.warnings if rules.get("word_policy") == "contextual" else res.violations
            target.append(
                {"category": "禁用词", "pattern": w, "count": c,
                 "where": _locations(paragraphs, w),
                 "hint": rules.get("replacements", {}).get(w, "")})

    for w, limit in rules.get("soft_words", {}).items():
        c = text.count(w)
        if c > limit:
            res.warnings.append(
                {"category": "高频词", "pattern": w, "count": c,
                 "where": _locations(paragraphs, w),
                 "hint": "超过阈值" + str(limit) + "，砍掉一半或换具体动作"})

    for pat in rules.get("patterns", []):
        found = re.findall(pat["regex"], text)
        n = len(found)
        limit = pat.get("limit", 0 if pat["severity"] == "hard" else 1)
        if n > limit:
            item = {"category": "句式", "pattern": pat["id"], "count": n,
                    "where": "全文" if n > 3 else _locations(
                        paragraphs, str(found[0])[:6] if found else ""),
                    "hint": pat.get("why", "")}
            (res.violations if pat["severity"] == "hard" and rules.get("word_policy") != "contextual"
             else res.warnings).append(item)

    ellip = m.get("ellipsis_per_paragraph_max", 1)
    for i, p in enumerate(paragraphs, 1):
        c = len(re.findall(r"…{1,2}", p))
        if c > ellip:
            res.warnings.append(
                {"category": "句式", "pattern": "省略号堆砌", "count": c,
                 "where": f"第{i}段", "hint": "一段最多用一次"})

    opener_max = m.get("same_para_opener_max", 2)
    para_heads = [p.strip()[:2] for p in paragraphs if p.strip()[:2]]
    i, best, cur = 0, 1, 1
    while i < len(para_heads) - 1:
        if re.match(r"^[\u4e00-\u9fff]", para_heads[i + 1] or "x") and \
                para_heads[i + 1] == para_heads[i] and \
                not para_heads[i].startswith(("「", "“", "-", "—")):
            cur += 1
            best = max(best, cur)
        else:
            cur = 1
        i += 1
    if best > opener_max:
        res.warnings.append(
            {"category": "句式", "pattern": "连续段同名开头",
             "count": best, "where": "全文", "hint": "换视角/用动作或环境起笔"})

    sents = _split_sentences(text)
    lens = [len(s) for s in sents]
    res.metrics = {
        "dialogue_ratio": _dialogue_ratio(text),
        "sentence_count": len(sents),
        "avg_sentence_len": round(sum(lens) / len(lens), 1) if lens else 0,
        "has_halfwidth_quote": bool(re.search(r"(^|[^0-9])\"[^\"]{2,}", text)),
    }

    run_len, maxRun = 1, 1
    for i in range(1, len(lens)):
        if lens[i] >= 10 and lens[i - 1] >= 10 and abs(lens[i] - lens[i - 1]) <= 2:
            run_len += 1
            maxRun = max(maxRun, run_len)
        else:
            run_len = 1
    res.metrics["max_same_len_run"] = maxRun
    same_max = m.get("max_same_len_run", 3)
    if maxRun > same_max:
        res.warnings.append(
            {"category": "节奏", "pattern": "连续同构句", "count": maxRun,
             "where": "全文", "hint": "打断节奏：接一句极短句或改标点"})

    dmin, dmax = m.get("dialogue_ratio_min", 0.25), m.get("dialogue_ratio_max", 0.5)
    if rules.get("enforce_dialogue_ratio", False) and any(q in text for q in ('“', '「', '"')):
        if res.metrics["dialogue_ratio"] < dmin:
            res.warnings.append(
                {"category": "对话占比", "pattern": "dialogue_low",
                 "count": res.metrics["dialogue_ratio"], "where": "全章",
                 "hint": f"对话仅{res.metrics['dialogue_ratio']:.0%}，建议{int(dmin*100)}%以上；把转述改回直接引语"})

    if res.metrics["has_halfwidth_quote"]:
        res.violations.append(
            {"category": "排版", "pattern": "半角引号", "count": 1,
             "where": "全文", "hint": "对白使用中文双引号“”，嵌套引用用‘’"})

    corner_quotes = re.findall(r"[「」『』]", text)
    if corner_quotes:
        res.violations.append(
            {"category": "排版", "pattern": "直角引号", "count": len(corner_quotes),
             "where": "全文", "hint": "将「」改为“”，将『』改为‘’"})

    return res


def main(argv):
    fp = Path(argv[1]) if len(argv) > 1 else None
    if not fp or not fp.exists():
        print("用法: python -m engine.style_kit.scanner <草稿.txt>")
        return 1
    text = fp.read_text(encoding="utf-8")
    r = scan(text)
    print(f"passed={r.passed}")
    print(f"metrics={json.dumps(r.metrics, ensure_ascii=False)}")
    for v in r.violations:
        print(f"  [违规] {v['category']} 「{v['pattern']}」x{v['count']} @{v['where']} {v.get('hint','')}")
    for w in r.warnings:
        print(f"  [提示] {w['category']} 「{w['pattern']}」x{w['count']} @{w['where']} {w.get('hint','')}")
    return 0 if r.passed else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
