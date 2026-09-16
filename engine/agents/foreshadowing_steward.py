# Foreshadowing Steward — 伏笔管家

import json
import logging
from engine.chapter_files import chapter_files
from engine.proxy import config

log = logging.getLogger("steward")


class ForeshadowingProtocolError(ValueError):
    pass


class ForeshadowingSteward:

    def __init__(self):
        self.model_config = config.foreshadowing_steward_model

    def audit(self, plan_json: dict, chapter_num: int,
              bible: dict) -> dict:
        all_fs = bible.get("clues", {}).get("active_foreshadowing", {})
        known = set(all_fs)
        planted = set()
        warnings = []
        clean_ops = []
        # 确定性协议检查：非法操作只丢弃并记警告，绝不中断整章生成。
        # （plan 由模型生成，虚构伏笔编号/重复 plant 是常见的模型模糊，不该成为硬错误。）
        for op in (plan_json.get("clue_operations") or []):
            fid = op.get("clue_id", "")
            action = op.get("action", "")
            if action == "plant":
                if fid in known or fid in planted:
                    warnings.append(f"重复 plant 已存在伏笔 {fid}，已忽略")
                    continue
                planted.add(fid)
            elif fid not in known and fid not in planted:
                warnings.append(f"{action} 指向未知伏笔 {fid}，已忽略")
                continue
            clean_ops.append(op)
        # 同步清掉非法操作，避免下游 archivist 再对虚构编号做伏笔归档
        plan_json["clue_operations"] = clean_ops

        prompt = self._build_prompt(plan_json, chapter_num, bible)
        result = self._call_llm(prompt)
        if not isinstance(result, dict):
            result = {}
        result["operation_warnings"] = warnings
        if warnings:
            log.warning(f"伏笔操作已清理: {warnings}")
        deterministic = {"overdue": [], "stale": []}
        for fid, item in all_fs.items():
            if item.get("status", "pending") in ("resolved", "retired"):
                continue
            hints = item.get("hinted_chapters") or []
            last_touch = item.get("last_hinted_chapter") or (
                max(hints) if hints else item.get("introduced_chapter", 0)
            )
            interval = item.get("touch_interval") or 30
            payoff = (item.get("payoff_end_chapter")
                      or item.get("intended_payoff_chapter"))
            if payoff and chapter_num >= payoff:
                deterministic["overdue"].append(fid)
            elif chapter_num - last_touch > interval:
                deterministic["stale"].append(fid)
        reminders = []
        for key, label in (("overdue", "到期未回收"), ("stale", "长期未触碰")):
            ids = list(dict.fromkeys(
                deterministic[key] + list(result.get(key, []) or [])
            ))
            result[key] = ids
            reminders.extend(f"{label}: {item}" for item in ids)
        result["reminders"] = reminders
        if reminders:
            log.warning(f"伏笔提醒: {reminders}")
        return result

    def _build_prompt(self, plan_json: dict, chapter_num: int,
                      bible: dict) -> str:
        from engine.prompts_loader import get_prompt
        system, _ = get_prompt("foreshadowing_steward")

        clues_data = bible.get("clues", {})
        all_fs = clues_data.get("active_foreshadowing", {})
        all_fs_json = json.dumps(all_fs, ensure_ascii=False, indent=2)
        ops = json.dumps(plan_json.get("clue_operations", []),
                         ensure_ascii=False, indent=2)
        plan_str = json.dumps(plan_json, ensure_ascii=False, indent=2)

        summaries = self._read_recent_summaries(chapter_num)

        return system.format(
            all_foreshadowing=all_fs_json,
            plan_json=plan_str,
            clue_operations=ops,
            recent_summaries=summaries,
            chapter_num=chapter_num,
        )

    def _read_recent_summaries(self, chapter_num: int) -> str:
        lines = []
        for fp in chapter_files(
            config.generated_dir, before_chapter=chapter_num, limit=5
        ):
            text = fp.read_text(encoding="utf-8")
            lines.append(text[:100] + "...")
        return "\n".join(lines) if lines else "无"

    def _call_llm(self, prompt: str) -> dict:
        from engine.llm_client import chat_json
        return chat_json(self.model_config, user_prompt=prompt)
