"""Create isolated novel workspaces without copying an existing novel."""

import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from engine.db import NovelDB
from engine.settings import NOVELS_DIR
from engine import model_config

_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")


class NovelCreationError(ValueError):
    """Invalid data supplied for a new novel."""


def validate_slug(novel_id: str) -> str:
    if not isinstance(novel_id, str) or not _SLUG_RE.fullmatch(novel_id):
        raise NovelCreationError("id 必须是安全 slug：仅允许小写字母、数字和连字符")
    return novel_id


def _validate_text(value: str, field: str, required: bool = False) -> str:
    if not isinstance(value, str) or (required and not value.strip()):
        raise NovelCreationError(f"{field} 不能为空")
    if len(value) > 10000:
        raise NovelCreationError(f"{field} 过长")
    return value.strip()


def _volume_config(chapter_count: int) -> dict:
    volumes = {}
    if chapter_count < 40:
        volume_count = 1
    else:
        minimum = (chapter_count + 79) // 80
        maximum = chapter_count // 40
        volume_count = min(maximum, max(minimum, round(chapter_count / 60)))
    for index in range(volume_count):
        start = index * chapter_count // volume_count + 1
        end = (index + 1) * chapter_count // volume_count
        volumes[f"volume_{index + 1}"] = {
            "name": f"第{index + 1}卷",
            "chapters": (start, end),
            "core_emotion": "推进、冲突、转折",
            "focus": "推进主线并发展人物关系",
        }
    return volumes


def _config_py(title: str, chapter_count: int, words_per_chapter: int, volumes: dict) -> str:
    return f'''"""Standalone configuration for this novel."""
from dataclasses import dataclass, field
from pathlib import Path

from engine.env_loader import load_env, root_env_path

PROJECT_ROOT = Path(__file__).resolve().parent
_LOCAL_ENV = load_env(local_path=PROJECT_ROOT / ".env", root_path=root_env_path(PROJECT_ROOT.parent))


def _env(name: str, default: str) -> str:
    return _LOCAL_ENV.get(name) or default


def _env_alias(*names: str, default: str) -> str:
    for name in names:
        if _LOCAL_ENV.get(name):
            return _LOCAL_ENV[name]
    return default


@dataclass
class ModelConfig:
    provider: str = "deepseek"
    model_name: str = "deepseek-chat"
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 0.9
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0

@dataclass
class Config:
    api_key: str = field(default_factory=lambda: _env_alias("API_KEY", "DEEPSEEK_API_KEY", default="your-api-key-here"))
    base_url: str = field(default_factory=lambda: _env_alias("API_BASE_URL", "DEEPSEEK_BASE_URL", default="https://api.deepseek.com/v1"))
    planner_model: ModelConfig = field(default_factory=lambda: ModelConfig(model_name=_env("PLANNER_MODEL", "deepseek-reasoner"), temperature=0.6))
    researcher_model: ModelConfig = field(default_factory=lambda: ModelConfig(model_name=_env("RESEARCHER_MODEL", "deepseek-reasoner"), temperature=0.15))
    writer_model: ModelConfig = field(default_factory=lambda: ModelConfig(model_name=_env("WRITER_MODEL", "deepseek-chat"), temperature=0.9, max_tokens=8192))
    immediate_reviewer_model: ModelConfig = field(default_factory=lambda: ModelConfig(model_name=_env("IMMEDIATE_REVIEWER_MODEL", "deepseek-chat"), temperature=0.15))
    heavy_reviewer_model: ModelConfig = field(default_factory=lambda: ModelConfig(model_name=_env("HEAVY_REVIEWER_MODEL", "deepseek-reasoner"), temperature=0.6))
    keeper_model: ModelConfig = field(default_factory=lambda: ModelConfig(model_name=_env("KEEPER_MODEL", "deepseek-chat"), temperature=0.15))
    archivist_model: ModelConfig = field(default_factory=lambda: ModelConfig(model_name=_env("ARCHIVIST_MODEL", "deepseek-chat"), temperature=0.15))
    story_keeper_model: ModelConfig = field(default_factory=lambda: ModelConfig(model_name=_env("STORY_KEEPER_MODEL", "deepseek-chat"), temperature=0.15))
    foreshadowing_steward_model: ModelConfig = field(default_factory=lambda: ModelConfig(model_name=_env("FORESHADOWING_STEWARD_MODEL", "deepseek-reasoner"), temperature=0.6))
    reader_proxy_model: ModelConfig = field(default_factory=lambda: ModelConfig(model_name=_env("READER_PROXY_MODEL", "deepseek-chat"), temperature=0.15))
    marketer_model: ModelConfig = field(default_factory=lambda: ModelConfig(model_name=_env("MARKETER_MODEL", "deepseek-chat"), temperature=0.9, max_tokens=8192))
    story_title: str = {title!r}
    chapter_count: int = {chapter_count}
    words_per_chapter: int = {words_per_chapter}
    language: str = "zh-CN"
    volume_config: dict = field(default_factory=lambda: {volumes!r})
    bible_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "bible")
    generated_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "generated")
    cache_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "cache")
    revision_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "revision")
    gate_fail_mode: str = _env("GATE_FAIL_MODE", "pending")
    immediate_review_max_retries: int = 3
    heavy_review_interval: int = 5
    chapter_edit_max_retries: int = 1
    max_retries: int = 3
    retry_delay: float = 2.0

config = Config()
'''


def _env_example() -> str:
    return '''# 复制为同目录的 .env，再填写本书使用的 API 配置和模型名称。
# .env 仅供本机使用，不要提交到 git。

# API_KEY 优先于 DEEPSEEK_API_KEY；二者任选其一。
API_KEY=your-api-key-here
DEEPSEEK_API_KEY=your-api-key-here
# API_BASE_URL 优先于 DEEPSEEK_BASE_URL。
API_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1

# 主题构思（新建小说前的全局主题生成使用；默认 deepseek-chat）
THEME_MODEL=deepseek-chat

# 各 Agent 使用的模型（可按本书单独调整）
PLANNER_MODEL=deepseek-reasoner
RESEARCHER_MODEL=deepseek-reasoner
WRITER_MODEL=deepseek-chat
IMMEDIATE_REVIEWER_MODEL=deepseek-chat
HEAVY_REVIEWER_MODEL=deepseek-reasoner
KEEPER_MODEL=deepseek-chat
ARCHIVIST_MODEL=deepseek-chat
STORY_KEEPER_MODEL=deepseek-chat
FORESHADOWING_STEWARD_MODEL=deepseek-reasoner
READER_PROXY_MODEL=deepseek-chat
MARKETER_MODEL=deepseek-chat

# 章节质量闸门失败模式：
#   pending = 未通过全部闸门的章节转入「待人工修订」队列（revision/），作家改完再发布（默认，推荐）
#   abort   = 沿用旧版硬失败：未过闸门即报错退出，正文不产出
GATE_FAIL_MODE=pending
'''


def _prompts(title: str, genre: str, description: str) -> dict:
    """新建小说的出厂提示词：人味 style_kit token + 完整占位符（与 agents 调用一致）。"""
    context = f"书名：《{title}》；类型：{genre or '未指定'}；简介：{description or '待创作'}"
    generic = "你是小说创作助手。请基于给定设定完成任务，保持人物和事实一致，直接输出结果。"
    return {
        "_meta": {"novel": title, "genre": genre, "description": description, "version": "2.0"},
        "planner": {"system": (
            "你是一位深谙番茄读者口味的网文结构师。【全局设定】【人物档案】【近期修改教训】"
            "都已在资料中，场景必须建立在这些设定之上，不得空降。请为《{novel_title}》第{chapter_num}章设计大纲。\n\n"
            "【规则】\n"
            "1. 按本章目标与字数预算安排1-4场，不为凑场景重复行动。明确主角想得到什么、主动做什么、"
            "遇到什么阻碍、实际得到或失去什么。升级经营必须展示能力的实际价值；其他类型兑现各自阅读期待。\n"
            "2. 先兑现已有期待，再发展新冲突；不能连续只受压、只遇怪事，没有有效进展。\n"
            "3. 及时承接上一章紧迫危机；只有因果允许才切日常，不固定延迟满足。\n"
            "4. 番茄钩子纪律：章末钩子必须是主角下一场景将直面且不可回避的具体悬念"
            "（新机会、主动决定、具体危机），来自本章结果，禁止只有莫名发热或声音的空钩子。\n"
            "5. 每场写出POV、起始状态和结束状态；后一场接前一场终态，已经完成的事件不得重演。\n"
            "输出严格 JSON（不要其他文字）：\n"
            "{{\"chapter_title\": \"...\", \"chapter_goal\": \"主角具体目标\", "
            "\"protagonist_action\": \"主动选择\", \"obstacle\": \"阻碍与代价\", "
            "\"payoff\": \"本章兑现的具体收益或答案\", \"carry_forward\": \"下一章具体目标\", "
            "\"emotional_arc\": [0.7, 0.9], "
            "\"scene_outline\": [{{\"scene_id\": 1, \"type\": \"high_conflict|breathable\", "
            "\"target_emotion\": 0.9, \"description\": \"...\", \"pov\": \"人物名\", "
            "\"start_state\": \"时间地点及行动进度\", \"end_state\": \"本场完成后的状态\", \"target_words\": 900}}], "
            "\"clue_operations\": [{{\"clue_id\": \"F001\", \"action\": \"plant|hint|escalate|reveal|reschedule|retire\", "
            "\"name\": \"...(仅 plant 必填: 伏笔名)\", \"description\": \"...(仅 plant 必填: 伏笔描述)\", \"method\": \"...\"}}], "
            "\"entities\": {{\"characters\": [], \"locations\": [], \"objects\": [], "
            "\"factions\": [], \"abilities\": [], \"clue_ids\": []}}, "
            "\"chapter_hooks\": {{\"light_hook\": \"...\", \"dark_hook\": \"...\"}}}}"
        ), "chapter_template": (
            "## 创作指令\n{instruction}\n\n"
            "## 当前卷\n- 卷名: {volume_name}\n- 核心情绪: {volume_emotion}\n- 篇幅重点: {volume_focus}\n\n"
            "## 全局设定\n{master_bible}\n\n"
            "## 人物档案\n{characters_json}\n\n"
            "## 线索网络\n{clues_json}\n\n"
            "## 母题库 (可用元素)\n{motif_bank_json}\n\n"
            "## 近期修改教训\n{lessons_learned}\n\n"
            "## 已写章节摘要\n{outline_summary}\n\n"
            "请为第 {chapter_num} 章撰写结构化大纲。"
        )},
        "outline_generator": {"system": generic + (
            "\n请根据世界观、人物和分卷规划生成指定单卷的章节大纲。只输出本卷内容，"
            "不要输出“## 第X卷”类卷标题，外层程序会统一包装。\n\n"
            "【精确模板】\n"
            "### 卷概览\n"
            "100-150字单段卷概览，不换行。\n\n"
            "### 第N-M章：小节名\n"
            "- **第N章 章名**：核心剧情（明确谁做什么导致什么）。*功能：该章的结构功能；伏笔：引入 F001*\n\n"
            "【硬性规则】\n"
            "1. 指定范围内每个章号恰好出现一次并连续升序，禁止跳号、重复或输出范围外章节。\n"
            "2. 每章严格一行且只能使用上述顶层bullet；章名2-6字；功能必填；伏笔只能写“引入 Fxxx”"
            "“推进 Fxxx”“回收 Fxxx”或“无”，Fxxx为三位数字编号。\n"
            "3. 小节标题严格使用“### 第N-M章：小节名”，范围须与下方章节一致。小节原则上8-12章；"
            "本卷不足8章时允许整卷单节；最后一节为贴合边界可少于8章。\n"
            "4. 禁止章节下附加二级bullet，禁止自查文本、重复卷总结、额外前言或结语、Markdown代码块及其他标题。\n"
            "最终答案必须从“### 卷概览”开始，写完本卷最后一章立即结束。"
        ), "chapter_template": ""},
        "title_generator": {"system": generic + "\n请根据以下大纲生成章名并输出 JSON：\n{outline}", "chapter_template": ""},
        "volume_summary": {"system": generic + "\n请总结《{volume_name}》（第{vol_start}-{vol_end}章）。\n核心情绪：{volume_emotion}\n章节摘要：\n{chapter_summaries}", "chapter_template": ""},
        "researcher": {"system": generic + "\n输出研究笔记（Markdown），只列与本章直接相关的事实。",
                        "chapter_template": "章节计划：{plan_json}\n知识库：{search_results}\n请输出第{chapter_num}章的研究笔记。"},
        "writer": {"system": (
            "你为番茄读者写连载小说。让人物有明确欲望、主动选择和可见的行动结果，"
            "兑现本书简介承诺的阅读体验，语言清楚自然。\n\n" + context + "\n\n"
            "请撰写《{novel_title}》第{chapter_num}章第{scene_id}场景。\n\n"
            "【上文缓存】{keeper_cache}\n【场景规划】{scene_plan}\n【人物声纹】{characters_voice_print}\n"
            "【资料包（以已定稿正文和作者设定为准，摘要矛盾需指出）】{research_context}\n【本章钩子】{chapter_hooks}\n"
            "【风格警戒·数据库惯性命中，务必回避】{style_watch}\n\n"
            "[STYLE_FORBIDDEN]\n\n"
            "【叙事方法，按场景需要选用】\n[STYLE_TECHNIQUES]\n\n"
            "【番茄连载纪律】\n[STYLE_TOMATO]\n\n"
            "【硬性约束】\n"
            "1. 对话服从任务与人物，允许完整句、简短转述、独处场景；不凑比例。\n"
            "2. 可直接写欲望、盘算和情绪，让动作与结果验证人物判断。\n"
            "3. 句式随内容变化，不机械碎句、不刻意安排长短交替。\n"
            "4. 开场接住上场终态，不重新出门、脱困、告别或重复已经完成的试验。\n"
            "5. 细节服务身份、冲突和行动；闲笔无配额，不用道具和回忆填字数。\n"
            "6. 严禁与上文缓存/资料包中的既有事实矛盾（伤势、位置、已揭露信息）。\n\n"
            "按本场景 target_words 预算写纯正文，允许约20%的浮动，短场景可以短。不要章节标题或场景编号，"
            "对话统一用中文双引号“”，嵌套引用用‘’，不用「」或【】包裹对白。只有最后一场写章末钩子。\n\n"
            "特殊条件：{special_condition}"
        )},
        "reviewer_immediate": {"system": (
            "你是连载小说责编，检查AI叙事的语义问题。用词与标点偏好不等于质量，"
            "不因正常连接词、完整句、心理描写、闲笔数量或对话比例打回。\n\n"
            "【上文缓存】\n{keeper_cache}\n\n【草稿】\n{draft}\n\n"
            "检查：1) 主角的目标、选择及后果是否清楚，是否完成本场任务；"
            "2) 是否重复上文已经完成的事件或倒退到旧状态；"
            "3) 是否靠堆叠细节、对话绕圈和反复试探拖延进展；"
            "4) 行为是否违背人物档案，视角是否越权；缺少声纹资料时不凭空判不匹配；"
            "5) 因果与时间地点是否连贯；长度服从本场预算，不设1000字最低值。\n\n"
            "paragraph 只写违规句前8字，suggestion 不超15字。输出 JSON（不要其他文本）：\n"
            "{{\"passed\": true, \"errors\": [{{\"type\": \"AI叙事|信息直塞|节奏断裂|声纹模糊|衔接断裂|字数不足\", "
            "\"paragraph\": \"前8字\", \"suggestion\": \"15字内修改方向\"}}]}}"
        )},
        "reviewer_heavy": {"system": (
            "你是有20年经验的资深网文责编。你最讨厌两件事：AI写的东西，和匠气十足但没有生命力的文字。"
            "注意：机械层禁用词由扫描器负责，你不要重复数字词。\n\n"
            "【章节规划大纲】\n{plan_json}\n\n【完整章节正文】\n{full_chapter}\n\n"
            "审查维度：\n1. 人物：对话符合人物利益、知识与已有声口吗？不强求废话、口癖和半句话。\n"
            "2. 细节可感度：抽象形容词代替感官？环境描写只调用视觉？\n"
            "3. 节奏：是否重复信息、拖延已承诺的结果？主角是否作出有效选择？\n"
            "4. 结构：伏笔操作是否生硬？章末钩子是否够硬？\n\n"
            "patch_instructions 必须具体到第X段第X句，不要给重写文本。输出 JSON：\n"
            "{{\"score\": 8.5, \"human_feel_issues\": \"...\", \"detail_issues\": \"...\", "
            "\"rhythm_issues\": \"...\", \"hook_issues\": \"...\", "
            "\"patch_instructions\": [\"第2段第3句明确行动结果\", \"第5段对话删掉已交代的信息\"]}}"
        )},
        "dialogue_auditor": {"system": (
            "你是对话声纹审计师，同时也是AI对话味道的专项猎手。\n\n"
            "【人物声纹档案】\n{voice_print}\n\n【当前场景正文】\n{draft}\n\n"
            "审计规则：\n"
            "1. 对话内容是否符合人物知识、利益和已有声口；没有档案时不猜测声纹。\n"
            "2. 是否循环重复信息、脱离情境讲道理，或让所有人只替主角解释设定。\n"
            "3. 允许完整回答、理性协商、自然转述和独处无对话。\n"
            "4. 不要求固定对话占比，不强加口癖、改口、废话或答非所问。\n"
            "5. 对白统一使用中文双引号“”，嵌套引用用‘’，不用「」或【】包裹对白。\n\n"
            "输出 JSON（不要其他文本）：\n"
            "{{\"passed\": true, \"violations\": [{{\"character\": \"人物名或整体\", "
            "\"issue\": \"声纹违规|AI对话|无法区分|占比异常\", \"location\": \"第几段或关键词前8字\", "
            "\"fix\": \"15字内修改方向\"}}]}}"
        )},
        "keeper": {"system": (
            "你是一个精准的记忆压缩器。请将场景正文(第{scene_id}号场景)压缩为不超过300字的运行时上下文。"
            "输出三个模块的 JSON（不要其他文本）：\n"
            "{{\"plot_progress\": \"客观事件链：谁在哪里做了什么拿到什么，谁受伤/死亡/发现什么；禁心理活动；不超过100字\", "
            "\"emotion_state\": \"主要人物当前情绪的身体反应和可观察行为；不超过80字\", "
            "\"env_and_clue\": \"时间/地点/天气可延续细节+新埋设伏笔+伏笔状态变化；不超过120字\"}}\n\n"
            "【场景正文】\n{scene_draft}"
        )},
        "archivist": {"system": (
            "你是小说档案员。输入为最终章节正文、本章结构化大纲与仅属于本章的逐场景快照摘要。"
            "只提取最终正文明确出现的信息，计划与旧快照不是已发生事实。"
            "confirmed_clue_operations 必须返回数组：仅保留正文确实完成的伏笔操作，"
            "每项附 evidence 原文短引；未完成的计划操作不要归档。重建时可依据正文补全操作。"
            "输出 JSON，不要其他文字，结构：\n"
            "{\n"
            "  \"character_updates\": {\"人物名\": {\"status_change\": \"一句话\", \"location\": \"所在地(未知则省略)\", \"injury_ability_item\": \"新伤/新能力/新物品(无则省略)\"}},\n"
            "  \"clue_updates\": {\"C001\": {\"current_state\": \"...\", \"new_development\": \"...\", \"resolved\": false}},\n"
            "  \"facts\": [{\"kind\": \"plot|object|location|injury|info|relationship\", \"subject\": \"人物或物品名\", \"content\": \"一句话原子事实25字内\", \"scene_id\": 1}],\n"
            "  \"confirmed_clue_operations\": [],\n"
            "  \"chapter_summary\": \"两句话不超过80字\"\n"
            "}\nfacts 是跨章一致性的长期记忆：谁拿到了什么/谁看见了什么/谁去了哪/什么东西被破坏/谁对谁说了什么关键信息。排除情绪描写，5-12条。"
        )},
        "story_check": {"system": (
            "你是长篇小说的故事逻辑审稿人。输入：跨章既有事实、读者开放问题、未回收承诺、"
            "上一章钩子、本场景规划与本场景草稿。\n\n"
            "【跨章既有事实】\n{facts}\n\n"
            "【读者开放问题】\n{open_questions}\n\n"
            "【未回收承诺】\n{promises}\n\n"
            "【上一章钩子（本章必须响应）】\n{hook}\n\n"
            "【上文缓存】\n{running_context}\n\n"
            "【本场景规划】\n{scene_plan}\n\n"
            "【本场景草稿】\n{draft}\n\n"
            "判定规则：\n"
            "1. 只把「与既有事实的字面矛盾」判违规——如前文某章写角色在甲地，"
            "本章草稿却写他在乙地，且正文没有任何转移/返回的过渡交代。\n"
            "2. 正常剧情发展（新冲突、新状态、合理转折）不算违规，除非与既有事实直接冲突。\n"
            "3. 钩子承接由整章负责，不要求每个场景回应同一个悬念；只检查本场任务与已发生事件的冲突。\n"
            "输出 JSON（不要其他文本）：\n"
            "{{\"passed\": true, \"errors\": [{{\"type\": \"事实矛盾|钩子未响应|开放问题无推进\", "
            "\"paragraph\": \"违规句前8字\", \"suggestion\": \"15字内修改方向\"}}], "
            "\"suggestions\": \"汇总修改方向，不超过80字\"}}"
        )},
        "story_keeper": {"system": (
            "你是长篇小说的故事管理员。输入为刚写完的章节正文与本章大纲，任务是抽取"
            "「可跨章验证的硬事实」，供下一章写作做连续性对账。只提取正文里明确写出的信息，"
            "禁止脑补推断。\n\n"
            "【上一章的读者开放问题】\n{prior_questions}\n\n"
            "【本章大纲】\n{plan_json}\n\n"
            "【本章正文】\n{full_chapter}\n\n"
            "输出 JSON（不要其他文本）：\n"
            "{\n"
            "  \"facts\": [{\"entity\": \"人物/地点/物品/势力名\", \"attribute\": \"位置|生死|身份|关系|能力|伤势|拥有|状态|目的 等\", \"value\": \"一句话原子事实\"}],\n"
            "  \"arc_updates\": [{\"character\": \"人物名\", \"goal\": \"当前目标(无则省略)\", \"fear\": \"恐惧(无则省略)\", \"secret\": \"隐藏的秘密(无则省略)\", \"conflict\": \"当下矛盾(无则省略)\", \"change\": \"本章关键变化(无则省略)\"}],\n"
            "  \"new_questions\": [\"本章新勾起的读者悬念（最多3条）\"],\n"
            "  \"resolved_question_ids\": [\"已在本章回答的开放问题 id\"]\n"
            "}\n"
            "facts 5-10 条，attribute 用有限集合里的短词。"
            "另输出 chapter_hooks:{light_hook:实际章末尚待处理的行动,dark_hook:正文支持的悬念}。"
            "位置、伤势、财产、能力属于可变状态，只有出生日期、既往经历等固定事实标记 immutable:true。"
        )},
        "foreshadowing_steward": {"system": (
            "你是伏笔管家，负责让伏笔在章节间有序运行。\n\n"
            "【当前所有伏笔】{all_foreshadowing}\n\n"
            "【本章大纲的伏笔操作】{clue_operations}\n\n"
            "【大纲】{plan_json}\n\n【近期章节摘要】{recent_summaries}\n\n"
            "检查本章大纲（第{chapter_num}章），操作协议为 plant/hint/escalate/reveal/reschedule/retire：\n"
            "1. 除plant外的操作指向的伏笔是否真实存在？\n"
            "2. plant是否重复埋设已存在伏笔？\n"
            "3. 有哪些pending伏笔长期未触碰（暗章数>30）需要提醒？\n"
            "4. 计划在本章回收但与当前章节差距过大的伏笔是否遗漏？\n"
            "输出JSON：{{\"operation_warnings\": [\"...\"], \"overdue\": [\"Fxxx\"], \"stale\": [\"Fxxx\"], \"duplicates\": [\"...\"]}}"
        )},
        "reader_proxy": {"system": (
            f"你是《{title}》的{genre}连载读者，关注这类作品许诺的阅读体验。你追到了前几章，"
            "没读过任何设定文档——正文里没讲的，你就是不知道。请逐段报告真实阅读感受。\n\n"
            "【章节正文】\n{full_chapter}\n\n"
            "规则：1) 每500字左右标记理解度/兴趣度(0-10)；2) 想发段评的记高光，想划走的记疲劳点，"
            "新名词没讲明白的记困惑点；3) 重点评估结尾：你会不会点开下一章？给面子没用，实话实说；"
            "4) 哪句像AI写的（工整像范文/排比/升华/背台词）记进 ai_suspect_points。\n\n"
            "输出 JSON（不要其他文本）：\n"
            "{{\"engagement_curve\": [{{\"position\": \"0-500字\", \"understanding\": 8, \"interest\": 6}}], "
            "\"confusion_points\": [\"...\"], \"fatigue_points\": [\"...\"], \"ai_suspect_points\": [\"...\"], "
            "\"best_moment\": \"...\", \"worst_moment\": \"...\", \"would_continue\": true, \"overall_score\": 7.5}}"
        )},
        "chapter_editor": {"system": (
            "你是整章编辑。逐段核对完整章节，不能只检查局部文风。输入含本章计划、前情、人物与完整正文。"
            "检查：重复脱困/进门/告别、跨场景时间倒退、人物位置和知识越权、固定经历矛盾、"
            "主角缺乏主动选择、本章承诺未兑现、连续受压没有有效进展、结尾空钩子。"
            "根据类型判断回报，日常或悬疑不强加战斗打脸；正常移动与成长不算设定矛盾。"
            "每条问题必须引用原文位置与可执行修改方向，不能仅凭偏好打回。"
            '输出JSON：{"passed":true,"errors":[],"suggestions":""}；'
            '有问题时passed=false，errors为[{"type":"问题类别","paragraph":"原文片段",'
            '"suggestion":"具体如何调整"}]。'
        )},
        "foundation": {"system": (
            "根据书名、类型、简介和已有作者设定补全开篇人物档案，不改作者明确事实。"
            "人物必须有具体欲望、眼前目标、底线、专业优势、能力边界和可辨认的说话习惯。"
            "只设计开篇必要的2-5人，不提前写后续剧情结果。"
            '输出JSON：{"characters":{"姓名":{"role":"主角或配角",'
            '"goal":"长期欲望","immediate_goal":"眼前目标","bottom_line":"底线",'
            '"expertise":"擅长什么","limits":"能力边界","voice_print":"声口",'
            '"immutable_facts":{"经历":"作者已确定的固定事实"}}}}。'
        )},
        "marketer": {
            "synopsis": "你是小说平台签约编辑。根据以下信息写一篇抓人的小说简介（200字以内，适合平台展示）。\n书名：{novel_title}\n核心设定：{world_setting}",
            "teaser": "为本书第{chapter_num}章「{chapter_title}」写一句50字以内的推荐语。\n本章内容：{chapter_summary}",
            "tags": "为本书起8-12个标签，帮助平台推荐。\n书名：{novel_title}\n世界观：{world_setting}",
            "author_note": "为作者写一段200字以内的「作者的话」，发布在章节旁边。亲切、不油腻。\n书名：{novel_title}\n创作理念：{inspiration}\n进度：{progress}",
            "cover_art": "为{novel_title}设计3套封面图AI绘画提示词（各100字内、中文画面描述）。\n世界观：{world_setting}",
            "character_portrait": "根据人物档案生成AI绘画立绘提示词（风格统一，200字内）。\n{character_profile}",
            "scene_illustration": "根据场景描述生成插图视觉提示词（150字内）。\n{scene_description}",
        },
    }


def _resolve_model_env(model: dict | None) -> dict:
    """把新建小说传入的模型配置解析成 {ENV_KEY: value}，校验后返回。

    支持两种写法：
      1. quick = {chat_model, reasoner_model, api_key?, base_url?}  → 一键覆盖全部角色
      2. models = {env或attr名: 值}                                    → 精确改个别角色
    两者可混用，models 优先级高于 quick。
    """
    if not model:
        return {}
    if not isinstance(model, dict):
        raise NovelCreationError("model 配置必须是对象")
    out = {}
    out.update(model_config.expand_quick(model.get("quick")))
    if model.get("models"):
        sanitized = model_config.sanitize_input(model["models"])
        out.update(sanitized)
    return out


def create_novel(id, title, chapter_count, words_per_chapter, genre, description,
                 model_env=None):
    """Create a novel directory atomically and return its final path.

    model_env：可选 {ENV_KEY: value}，创建时写入 novels/<id>/.env（密钥只存本书 .env）。
    """
    novel_id = validate_slug(id)
    title = _validate_text(title, "title", required=True)
    genre = _validate_text(genre, "genre")
    description = _validate_text(description, "description")
    if not isinstance(chapter_count, int) or isinstance(chapter_count, bool) or not 1 <= chapter_count <= 100000:
        raise NovelCreationError("chapter_count 必须是 1 到 100000 的整数")
    if not isinstance(words_per_chapter, int) or isinstance(words_per_chapter, bool) or not 1 <= words_per_chapter <= 1000000:
        raise NovelCreationError("words_per_chapter 必须是正整数")

    root = NOVELS_DIR.resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / novel_id
    if target.exists():
        raise FileExistsError(f"小说 id 已存在: {novel_id}")
    volumes = _volume_config(chapter_count)
    temp_dir = Path(tempfile.mkdtemp(prefix=f".{novel_id}-", dir=str(root)))
    try:
        (temp_dir / "bible").mkdir()
        (temp_dir / "generated").mkdir()
        (temp_dir / "cache").mkdir()
        (temp_dir / "revision").mkdir()
        (temp_dir / "config.py").write_text(_config_py(title, chapter_count, words_per_chapter, volumes), encoding="utf-8")
        (temp_dir / ".env.example").write_text(_env_example(), encoding="utf-8")
        if model_env:
            model_config.update_env_file(temp_dir / ".env", model_env)
        (temp_dir / "novel_prompts.json").write_text(json.dumps(_prompts(title, genre, description), ensure_ascii=False, indent=2), encoding="utf-8")
        (temp_dir / "bible" / "master_bible.md").write_text(f"# {title}\n\n## 类型\n{genre}\n\n## 简介\n{description}\n", encoding="utf-8")
        (temp_dir / "bible" / "characters.json").write_text(json.dumps({"characters": {}}, ensure_ascii=False, indent=2), encoding="utf-8")
        (temp_dir / "bible" / "clues.json").write_text(json.dumps({"clues": {}, "active_foreshadowing": {}}, ensure_ascii=False, indent=2), encoding="utf-8")
        (temp_dir / "bible" / "motif_bank.json").write_text(json.dumps({"motifs": []}, ensure_ascii=False, indent=2), encoding="utf-8")
        (temp_dir / "bible" / "lessons_learned.jsonl").write_text("", encoding="utf-8")
        titles = {"_schema": "1.0", "_description": "章节标题库", "volumes": {}}
        for key, volume in volumes.items():
            lo, hi = volume["chapters"]
            titles["volumes"][key] = {"name": volume["name"], "range": [lo, hi], "synopsis": volume["focus"], "chapters": {str(n): f"第{n}章" for n in range(lo, hi + 1)}}
        (temp_dir / "bible" / "chapter_titles.json").write_text(json.dumps(titles, ensure_ascii=False, indent=2), encoding="utf-8")
        db = NovelDB(temp_dir)
        try:
            db.ensure_imported()
        finally:
            db.close()
        for attempt in range(5):
            try:
                os.replace(str(temp_dir), str(target))
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.02 * (2 ** attempt))
        return target
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
