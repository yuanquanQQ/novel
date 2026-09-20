"""Validation shared by semantic reviewers and chapter-level editing."""

import re


def word_count(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9]+", text))


def validate_verdict(result, field="errors") -> dict:
    if (not isinstance(result, dict) or type(result.get("passed")) is not bool
            or not isinstance(result.get(field), list)
            or any(not isinstance(item, dict) for item in result[field])):
        return {
            "passed": False, field: [], "unavailable": True,
            "suggestions": "审阅结果缺失或格式错误，需要重新审阅。",
        }
    return dict(result, passed=result["passed"] and not result[field])


def reader_feedback(result) -> list[str]:
    if (not isinstance(result, dict)
            or type(result.get("would_continue")) is not bool
            or isinstance(result.get("overall_score"), bool)
            or not isinstance(result.get("overall_score"), (int, float))
            or not 0 <= result["overall_score"] <= 10):
        return ["读者审阅结果不完整，需要重新评估。"]
    issues = []
    for key in ("confusion_points", "fatigue_points"):
        points = result.get(key, [])
        if not isinstance(points, list):
            return ["读者审阅问题列表格式错误，需要重新评估。"]
        issues.extend(str(point) for point in points if point)
    if not result["would_continue"]:
        issues.append("续读意愿不足：兑现本章核心期待，并给出下一步具体目标。")
    if result["overall_score"] < 6:
        issues.append("阅读评分低于6分，需处理主角目标、因果或回报的缺口。")
    return issues


def edit_chapter(text, plan, chapter, context, config, writer, reviewers, reader, auditor):
    """Review the actual merged text, then repair and recheck a bounded number of times."""
    from engine.style_kit import scanner
    from engine.agents.story_keeper import story_check

    history = []
    limit = max(0, min(3, int(getattr(config, "chapter_edit_max_retries", 1))))
    for attempt in range(limit + 1):
        scan = scanner.scan(text)
        editorial = validate_verdict(reviewers.chapter_check(text, plan, chapter, context))
        dialogue = validate_verdict(auditor.audit(text, context, "chapter"), "violations")
        logic = validate_verdict(story_check(context.get("_story_state", {}), chapter,
                                            plan, text, {"running_context": ""}))
        try:
            response = reader.read(text)
        except Exception:
            response = {}
        issues = reader_feedback(response)
        for verdict, field in ((editorial, "errors"), (dialogue, "violations"), (logic, "errors")):
            if not verdict["passed"]:
                issues.append(verdict.get("suggestions") or str(verdict.get(field)) or "审阅未通过")
        if not text.strip():
            issues.append("正文为空")
        budget = plan.get("target_words")
        if isinstance(budget, (int, float)) and budget > 0 and not budget * .8 <= word_count(text) <= budget * 1.2:
            issues.append(f"本章约{word_count(text)}字，偏离{budget}字预算超过20%，删冗余或补必要剧情，不灌水。")
        if not scan.passed:
            issues.append(scan.to_suggestions())
        history.append({"attempt": attempt + 1, "issues": issues, "editorial": editorial,
                        "dialogue": dialogue, "story": logic, "reader": response})
        if not issues or attempt == limit:
            return text, scan, response, history, not issues
        if any(v.get("unavailable") for v in (editorial, dialogue, logic)):
            return text, scan, response, history, False
        text = writer.apply_patches(text, plan, issues, chapter)
    raise AssertionError("unreachable")
