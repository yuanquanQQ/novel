# Story Keeper — 作家笔记本：故事状态、连续性对账、角色弧线、悬念台账
#
# 职责（审阅不可用不放行，发布阶段提取失败触发回滚）：
#   1. 每章写完后抽出结构化事实，与历史事实做连续性对账，发现矛盾写进 continuity_warnings；
#   2. 维护角色弧线（目标/恐惧/秘密/矛盾/关键变化）；
#   3. 维护读者开放问题（悬念）与未回收承诺（伏笔台账）；
#   4. 记录每章钩子，供下一章响应用。
# 产出：bible/story_state.json，被 planner 与 writer 消费。

import json
import logging
import os
import tempfile
from pathlib import Path

from engine.proxy import config

log = logging.getLogger("story_keeper")

# 固定事实才自动判矛盾，位置和伤势等动态属性允许随剧情变化。
HARD_ATTRIBUTES = {"出生地", "出生日期", "血缘", "既往经历", "印记位置"}
_MAX_WARNINGS = 12      # continuity_warnings 最多保留条数
_MAX_CLOSED_QUESTIONS = 12  # 仅裁剪已解决的问题，未解决的悬念全部保留。
_MAX_HOOK_LOG = 20


def _empty_state() -> dict:
    return {
        "facts": {},            # {entity: {attribute: {value, chapters}}}
        "character_arcs": {},   # {name: {goal, fear, secret, conflict, change, last_chapter}}
        "open_questions": [],   # [{id, text, raised_chapter, status, resolved_chapter}]
        "unresolved_promises": {},  # {fid: {name, planted_chapter, status, last_touched_chapter}}
        "continuity_warnings": [],  # [{chapter, entity, attribute, prior, now, severity}]
        "hook_log": [],             # [{chapter, light, dark, carried_into}]
        "last_updated": 0,
    }


def _norm(text) -> str:
    return " ".join(str(text or "").split())


class StoryKeeperAgent:

    def __init__(self):
        # 支持离线人工归档；需要模型时由调用阶段报告不可用。
        try:
            self.model_config = (
                getattr(config, "story_keeper_model", None)
                or getattr(config, "writer_model", None)
            )
        except Exception:
            self.model_config = None

    # ---------------- 存取 ----------------
    def load_state(self, bible_dir) -> dict:
        fp = Path(bible_dir) / "story_state.json"
        if not fp.exists():
            return _empty_state()
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            merged = _empty_state()
            for key in merged:
                if key in data:
                    merged[key] = data[key]
            merged["last_updated"] = int(data.get("last_updated", 0))
            return merged
        except (OSError, ValueError) as exc:
            log.warning(f"story_state.json 读取失败，按空状态继续: {exc}")
            return _empty_state()

    def save_state(self, bible_dir, state: dict) -> Path:
        fp = Path(bible_dir) / "story_state.json"
        fp.parent.mkdir(parents=True, exist_ok=True)
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=fp.parent,
                prefix=fp.name + ".", suffix=".tmp", delete=False,
            ) as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
                tmp = handle.name
            os.replace(tmp, fp)
            tmp = None
        finally:
            if tmp:
                Path(tmp).unlink(missing_ok=True)
        return fp

    # ---------------- 每章状态更新 ----------------
    def update_state(self, bible_dir, chapter_num: int,
                     plan_json: dict, keeper_cache: dict,
                     full_chapter: str, *, extraction=None) -> dict:
        """抽取本章故事要素 → 对账 → 合并 → 落盘。返回更新后的 state。"""
        state = self.load_state(bible_dir)
        if extraction is None:
            extraction = self._extract(bible_dir, chapter_num, plan_json, full_chapter, state)
        if not isinstance(extraction, dict) or not isinstance(extraction.get("facts"), list):
            raise ValueError("故事状态抽取缺少 facts，不能标记为已更新")
        if isinstance(extraction, dict):
            self._merge_facts(state, chapter_num, extraction.get("facts", []))
            self._merge_arcs(state, chapter_num, extraction.get("arc_updates", []))
            self._merge_questions(state, chapter_num, extraction.get("new_questions", []),
                                  extraction.get("resolved_question_ids", []))
            self._sync_promises(state, bible_dir)
            self._log_hooks(state, chapter_num, {"chapter_hooks": extraction.get("chapter_hooks", {})})
        state["last_updated"] = chapter_num
        from engine.authoring import overlay_story
        overlay_story(Path(bible_dir).parent, chapter_num, state)
        self.save_state(bible_dir, state)
        return state

    def _extract(self, bible_dir, chapter_num: int, plan_json: dict,
                 full_chapter: str, state: dict) -> dict:
        from engine.llm_client import chat_json
        from engine.prompts_loader import get_prompt
        system, _ = get_prompt("story_keeper")
        prior_questions = "\n".join(
            f"{q.get('id')} {q.get('text', '')}"
            for q in state.get("open_questions", []) if q.get("status") == "open"
        ) or "（无）"
        # 提示词含 JSON 示例字面花括号，禁用 str.format，用占位符替换
        prompt = (
            system
            .replace("{chapter_num}", str(chapter_num))
            .replace("{prior_questions}", prior_questions)
            .replace("{plan_json}", json.dumps(plan_json, ensure_ascii=False, indent=2))
            .replace("{full_chapter}", full_chapter)
        )
        result = chat_json(self.model_config, user_prompt=prompt)
        return result if isinstance(result, dict) else {}

    # ---------------- 确定性对账 ----------------
    def _merge_facts(self, state: dict, chapter_num: int, facts: list):
        if not isinstance(facts, list):
            return
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            entity = _norm(fact.get("entity"))
            attribute = _norm(fact.get("attribute"))
            value = _norm(fact.get("value"))
            if not entity or not attribute or not value:
                continue
            bucket = state["facts"].setdefault(entity, {})
            prior = bucket.get(attribute)
            if (prior is not None and _norm(prior.get("value")) != value
                    and (attribute in HARD_ATTRIBUTES or fact.get("immutable") is True)):
                self._record_warning(state, {
                    "chapter": chapter_num,
                    "entity": entity,
                    "attribute": attribute,
                    "prior": prior.get("value"),
                    "now": value,
                    "severity": "major" if attribute in HARD_ATTRIBUTES else "minor",
                })
            chapters = list(dict.fromkeys(
                list(prior.get("chapters", [])) + [chapter_num])) if prior else [chapter_num]
            bucket[attribute] = {"value": value, "chapters": chapters}

    def _record_warning(self, state: dict, warning: dict):
        state.setdefault("continuity_warnings", []).append(warning)
        state["continuity_warnings"] = state["continuity_warnings"][-_MAX_WARNINGS:]

    def _merge_arcs(self, state: dict, chapter_num: int, arc_updates: list):
        if not isinstance(arc_updates, list):
            return
        for update in arc_updates:
            if not isinstance(update, dict):
                continue
            name = _norm(update.get("character"))
            if not name:
                continue
            arc = state["character_arcs"].setdefault(name, {})
            for key in ("goal", "fear", "secret", "conflict", "change"):
                if update.get(key):
                    arc[key] = _norm(update[key])
            arc["last_chapter"] = chapter_num

    def _merge_questions(self, state: dict, chapter_num: int,
                         new_questions, resolved_ids):
        if isinstance(new_questions, list):
            for text in new_questions[:3]:
                text = _norm(text)
                if not text:
                    continue
                qid = f"Q{chapter_num:03d}{len(state['open_questions']) + 1:02d}"
                state["open_questions"].append({
                    "id": qid, "text": text[:40],
                    "raised_chapter": chapter_num,
                    "status": "open", "resolved_chapter": None,
                })
        if isinstance(resolved_ids, list):
            resolved = set(str(i) for i in resolved_ids)
            for q in state["open_questions"]:
                if q.get("status") == "open" and q.get("id") in resolved:
                    q["status"] = "resolved"
                    q["resolved_chapter"] = chapter_num
        closed = [q for q in state["open_questions"] if q.get("status") != "open"][-_MAX_CLOSED_QUESTIONS:]
        state["open_questions"] = [q for q in state["open_questions"] if q.get("status") == "open" or q in closed]

    def _sync_promises(self, state: dict, bible_dir):
        """以 clues.json 的 active_foreshadowing 为权威，重建未回收承诺台账。"""
        clues_fp = Path(bible_dir) / "clues.json"
        foreshadowing = {}
        if clues_fp.exists():
            try:
                foreshadowing = json.loads(
                    clues_fp.read_text(encoding="utf-8")
                ).get("active_foreshadowing", {})
            except (OSError, ValueError) as exc:
                log.warning(f"clues.json 读取失败，伏笔台账跳过: {exc}")
        fresh = {}
        for fid, item in foreshadowing.items():
            if item.get("status") in ("resolved", "retired"):
                continue
            fresh[fid] = {
                "name": item.get("name", ""),
                "planted_chapter": item.get("introduced_chapter"),
                "status": item.get("status", "pending"),
                "last_touched_chapter": item.get("last_hinted_chapter"),
                "intended_payoff_chapter": item.get("intended_payoff_chapter"),
                "payoff_end_chapter": item.get("payoff_end_chapter"),
            }
        # 保留已解决记录但不再进 planner/writer 上下文
        state["unresolved_promises"] = fresh

    def _log_hooks(self, state: dict, chapter_num: int, plan_json: dict):
        hooks = plan_json.get("chapter_hooks", {})
        state.setdefault("hook_log", []).append({
            "chapter": chapter_num,
            "light": hooks.get("light_hook", ""),
            "dark": hooks.get("dark_hook", ""),
            "carried_into": chapter_num + 1,
        })
        state["hook_log"] = state["hook_log"][-_MAX_HOOK_LOG:]


# ============================================================
# 模块级上下文构建（planner / writer 复用，不依赖 agent 实例）
# ============================================================

def load_bare_state(bible_dir) -> dict:
    """模块级读取 story_state.json（供 planner/writer 直接消费，无需实例化）。"""
    try:
        return StoryKeeperAgent().load_state(bible_dir)
    except Exception as exc:
        log.warning(f"story_state 读取失败，按空状态继续: {exc}")
        return _empty_state()


def planner_context(state: dict, chapter_num: int, query=None) -> str:
    """给 planner 的故事状态上下文：承诺、开放问题、角色弧线、连续性警告。"""
    from engine.memory import select_memory
    state = select_memory(state, chapter_num, query)
    lines = []
    pending = [p for p in state.get("unresolved_promises", {}).values()
               if p.get("status") != "resolved"]
    if pending:
        lines.append("未回收承诺（读者在等）：")
        for p in pending:
            planted = p.get("planted_chapter")
            lines.append(f"- {p.get('name', '')}（第{planted or '?'}章种下）")
    open_qs = [q for q in state.get("open_questions", [])
               if q.get("status") == "open"]
    if open_qs:
        lines.append("读者开放问题：")
        lines += [f"- {q['text']}" for q in open_qs]
    arcs = state.get("character_arcs", {})
    if arcs:
        lines.append("角色弧线快照：")
        for name, arc in arcs.items():
            bits = []
            if arc.get("goal"): bits.append(f"目标:{arc['goal']}")
            if arc.get("fear"): bits.append(f"恐惧:{arc['fear']}")
            if arc.get("secret"): bits.append(f"秘密:{arc['secret']}")
            if arc.get("conflict"): bits.append(f"矛盾:{arc['conflict']}")
            if arc.get("change"): bits.append(f"近变:{arc['change']}")
            if bits:
                lines.append(f"- {name}：{'；'.join(bits)}")
    warnings = [w for w in state.get("continuity_warnings", [])
                if w.get("chapter", 0) < chapter_num]
    if warnings:
        lines.append("连续性警告：")
        lines += [f"- [第{w['chapter']}章] {w['entity']}·{w['attribute']}: "
                  f"「{w['prior']}」→「{w['now']}」" for w in warnings]
    return "\n".join(lines) if lines else "(尚无故事状态)"


def writer_warnings(state: dict, chapter_num: int, query=None) -> str:
    """给 writer 的连续性警告：只保留会对本章造成约束的最关键几条。"""
    from engine.memory import select_memory
    state = select_memory(state, chapter_num, query)
    parts = []
    warnings = [w for w in state.get("continuity_warnings", [])
                if w.get("chapter", 0) < chapter_num]
    if warnings:
        parts.append("【故事连续性警告——本章写作必须处理或回避】")
        for w in warnings:
            tag = "严重矛盾" if w.get("severity") == "major" else "细节变化"
            parts.append(f"- [第{w['chapter']}章] {w['entity']}·{w['attribute']}: "
                         f"前文「{w['prior']}」→ 本章写「{w['now']}」（{tag}）")
    open_qs = [q for q in state.get("open_questions", [])
               if q.get("status") == "open"]
    if open_qs:
        parts.append("【读者此刻在追问（本章应回应或推进）】")
        parts += [f"- {q['text']}" for q in open_qs]
    pending = [p for p in state.get("unresolved_promises", {}).values()
               if p.get("status") != "resolved"]
    if pending:
        parts.append("【未回收承诺（读者在等）】")
        parts += [f"- {p.get('name', '')}（第{p.get('planted_chapter') or '?'}章种下）"
                  for p in pending]
    if state.get("hook_log"):
        last = state["hook_log"][-1]
        if last.get("chapter") == chapter_num - 1:
            parts.append("【上一章钩子（本章必须响应）】")
            if last.get("light"): parts.append(f"- 明钩: {last['light']}")
            if last.get("dark"): parts.append(f"- 暗钩: {last['dark']}")
    return "\n".join(parts)


def story_check(state: dict, chapter_num: int, scene: dict,
                draft: str, keeper_cache: dict) -> dict:
    """故事逻辑闸门：草稿是否与既有跨章事实矛盾、是否无视必须响应的承诺/钩子/开放问题。

    与风格扫描、语义审、声纹审计并列的一道 LLM 闸门。
    无模型、网络异常或响应格式错误时不放行，交由待修订流程处理。
    """
    from engine.memory import select_memory
    state = select_memory(state or {}, chapter_num, dict(scene, draft=draft))
    try:
        from engine.llm_client import chat_json
        from engine.prompts_loader import get_prompt
        system, _ = get_prompt("story_check")
        facts = state.get("facts", {})
        fact_lines = []
        for entity, attrs in facts.items():
            for attr, v in attrs.items():
                chapters = v.get("chapters", [])
                fact_lines.append(
                    f"- {entity}·{attr}：{v.get('value', '')}（第{','.join(map(str, chapters))}章）"
                )
        open_qs = [q.get("text", "") for q in state.get("open_questions", [])
                   if q.get("status") == "open"]
        pending = [p.get("name", "") for p in state.get("unresolved_promises", {}).values()
                   if p.get("status") != "resolved"]
        hook = ""
        if state.get("hook_log"):
            last = state["hook_log"][-1]
            if last.get("chapter") == chapter_num - 1:
                hook = f"{last.get('light') or ''}；{last.get('dark') or ''}".strip("；")
        running = (keeper_cache or {}).get("running_context", "")
        model = getattr(config, "story_keeper_model", None) or getattr(config, "writer_model", None)
        # 提示词含 JSON 示例字面花括号，用占位符替换而非 str.format
        prompt = (
            system
            .replace("{chapter_num}", str(chapter_num))
            .replace("{facts}", "\n".join(fact_lines) or "（暂无跨章事实）")
            .replace("{open_questions}", "\n".join(f"- {q}" for q in open_qs) or "（无）")
            .replace("{promises}", "\n".join(f"- {p}" for p in pending) or "（无）")
            .replace("{hook}", hook or "（无）")
            .replace("{running_context}", running or "（无）")
            .replace("{scene_plan}", json.dumps(scene, ensure_ascii=False, indent=2))
            .replace("{draft}", draft)
        )
        result = chat_json(model, user_prompt=prompt)
        from engine.quality import validate_verdict
        return validate_verdict(result)
    except Exception as exc:
        log.warning(f"StoryKeeper 故事逻辑闸门不可用: {exc}")
        return {"passed": False, "errors": [], "unavailable": True,
                "suggestions": "故事逻辑审阅不可用，需要重新审阅。"}


def record_actual_events(config, chapter_num: int, plan_json: dict,
                         keeper_cache: dict) -> str:
    """章节级大纲追认：把 archivist 已归档的本章摘要追加进 bible/actual_timeline.md。

    planner 每章读取该轨迹，「已写章节以实际为准，大纲为原计划」——大纲随实际演化。
    非致命：DB 不可用或无摘要时跳过。
    """
    try:
        from engine.db import NovelDB
        from engine.settings import get_novel_dir
        db = NovelDB(get_novel_dir())
        try:
            row = db.conn.execute(
                "SELECT summary FROM chapter_summaries WHERE chapter=?",
                (chapter_num,),
            ).fetchone()
        finally:
            db.close()
        summary = (row["summary"] if row else "").strip() or "（无归档摘要）"
    except Exception as exc:
        log.warning(f"实际轨迹摘要读取失败: {exc}")
        summary = "（无归档摘要）"
    title = (plan_json or {}).get("chapter_title") or f"第{chapter_num}章"
    entry = f"- 第{chapter_num}章《{title}》：{summary}"
    fp = Path(config.bible_dir) / "actual_timeline.md"
    try:
        fp.parent.mkdir(parents=True, exist_ok=True)
        lines = fp.read_text(encoding="utf-8").splitlines() if fp.exists() else []
        # 同章重写时原位替换，保持时间线稳定
        import re
        lines = [ln for ln in lines if re.match(r"^- 第\d+章", ln)
                 and not ln.startswith(f"- 第{chapter_num}章")]
        lines.append(entry)
        lines.sort(key=lambda ln: int(re.match(r"^- 第(\d+)章", ln).group(1)))
        body = "## 已实际发生的叙事轨迹\n" + "\n".join(lines) + "\n"
        fp.write_text(body, encoding="utf-8")
    except OSError as exc:
        log.warning(f"实际轨迹写入失败: {exc}")
        return ""
    return entry


def append_volume_revisions(config, volume_num: int, summary_text: str) -> str:
    """卷末总结后：产出修订建议回流传给下一卷规划，追加到 bible/volume_revisions.md。"""
    vol = getattr(config, "volume_config", {}).get(f"volume_{volume_num}")
    if not vol:
        return ""
    lo, hi = vol["chapters"]
    from engine.llm_client import chat
    total = getattr(config, "chapter_count", 0) or max(hi, 100)
    prompt = (
        "你是长篇小说的主编。下面是第{n}卷（第{lo}-{hi}章）的卷末总结。"
        "请站在全书 {total} 章的宏观结构上，给出对下一卷规划的修订建议："
        "节奏问题、该收的线、该埋的钩子、人物关系该往哪走、避免重复的情节套路。"
        "输出 3-6 条简洁的修订要点，每行一条，直接给内容不要解释。\n\n"
        "【第{n}卷总结】\n{summary}"
    ).format(n=volume_num, lo=lo, hi=hi, total=total, summary=summary_text)
    try:
        model = getattr(config, "story_keeper_model", None) or config.writer_model
        revisions = chat(model, user_prompt=prompt).strip()
    except Exception as exc:
        log.warning(f"卷修订建议生成失败: {exc}")
        return ""
    if not revisions:
        return ""
    fp = Path(config.bible_dir) / "volume_revisions.md"
    fp.parent.mkdir(parents=True, exist_ok=True)
    block = (f"\n## 第{volume_num}卷（第{lo}-{hi}章）修订建议\n"
             f"（供第{volume_num + 1}卷规划遵循）\n{revisions}\n")
    existing = fp.read_text(encoding="utf-8") if fp.exists() else ""
    fp.write_text(existing.rstrip() + "\n" + block, encoding="utf-8")
    log.info(f"卷修订建议已追加: {fp}")
    return block
