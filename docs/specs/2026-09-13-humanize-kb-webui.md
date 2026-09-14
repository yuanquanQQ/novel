# Spec: 人味提示词升级 + 每小说 SQLite 知识库 + Vue 全流程控制台

日期：2026-09-13　状态：**已实施**（25/25 测试通过：scanner 9 + db 7 + server API 9；Vite 构建成功；uvicorn 真机冒烟通过）
确认意图（interview-me 产出）：生成正文"没有人味"是核心痛点；目标是番茄小说平台可读的连载文；每本小说建结构化数据库记录人物/伏笔/事实/教训；Vue 前端做全流程控制台。

## 1. Objective

三条工作线，按依赖顺序 A → B → C：

**A. 提示词人味化（番茄向）**
现状问题：writer/reviewer 提示词只做了"禁"（不写什么），缺"导"（怎么写得像人）；禁用词扫描靠 LLM 自报，经常漏；无番茄平台特征（章末必留追读钩、金句式口语、节奏跟随情绪）。
方案：
1. 新建引擎级共享风格库 `engine/style_kit/`（不散落在各小说 prompts 里）：
   - `banned_words.json` — 结构化词表（词汇类 / 句式类 / 模板道具类 / AI情绪万能句），源自 novel-live-writing `references/banned-words.md`，含替换方向，前端可编辑
   - `techniques.md` — 正向技法注入（源自 techniques.md 30 招中的核心 15 招：情绪体感化、私人细节、句式情绪同步、干扰项注入、主角犯错、感官偏见、白描比喻克制、标点语流、对话碎化、长短错落、一句成段、数字体感化、无用道具、减空洞加颗粒、电影桥段化）
   - `tomato_rules.md` — 番茄平台规则：单章 1800-2500 字、每 800 字一个小爽点/转折、章末硬钩子、开篇 3 秒进入冲突、对话「」直角引号、破折号清零
2. 重写两本小说 `novel_prompts.json` 的 writer / reviewer_immediate / reviewer_heavy / dialogue_auditor / reader_proxy / planner prompt：注入"导"的部分（正向技法+番茄规则），由 `prompts_loader` 在运行时把 style_kit 内容拼入，禁改剧本类约束保留
3. **确定性预检**：`engine/style_kit/scanner.py`（纯代码，非 LLM）对草稿做禁用词/句式 regex 扫描 + 句长分布、对话占比、连续同构句统计 → 违规先由代码打回（零成本、必命中），LLM Reviewer 只审语义层（声纹、衔接、人味整体感）；扫描结果写入数据库

**B. 每小说 SQLite 知识库（记录型数据库）**
- 新文件 `engine/db.py`，stdlib `sqlite3`，路径 `novels/<name>/db/novel.db`，WAL 模式
- Schema（v1）：
  - `characters(name, role, profile_json, voice_print, first_chapter, updated_chapter)`
  - `character_states(chapter, character, state_json)` — 每章状态时间线
  - `foreshadowing(id, name, status, planted_ch, hinted_chs(JSON), payoff_ch, resolved_ch, description)` — 生命周期可查"过期/30章未碰"
  - `chapter_facts(chapter, kind[plot/object/location/injury/info], subject, content, scene_id)` — 从 Keeper 快照提取的原子事实，供跨章检索防前后矛盾
  - `style_hits(chapter, category, pattern, count)` — scanner 命中记录（喂给 lessons 飞轮：高频违规词自动置顶进 writer 注意事项）
  - `lessons(chapter, issue, fix, source)`
  - `chapter_log(chapter, title, status, words, reader_score, hook_type(s), would_continue, created_at)`
- Bible JSON 仍是"种子/出厂设定"；DB 是"运行时记忆"。首次 `init_db` 从 bible/*.json 幂等导入；之后 Archivist/Keeper 双写（JSON 保持向后兼容）
- Researcher 改为**查询驱动**：按本章 plan 的场景出场人物查 character_states 最近 3 次 + 未回收伏笔（按 hinted_chs 距离排序，过期优先）+ 相关 chapter_facts（关键词 LIKE 匹配）+ style_hits Top5 → 拼精准资料包，替代现在整库 JSON 截断塞入
- CLI：`db init`（显式导入命令）、`status` 增 DB 统计行；`view bible` 显示 db 文件大小

**C. Vue 全流程控制台**
- `server/`：FastAPI 薄服务（新依赖 fastapi+uvicorn），REST + SSE
  - 读：chapters/outline/titles/bible/DB 统计/进度 → 直接读文件或查 SQLite
  - 写：保存章节 md、编辑 style_kit/bible JSON
  - 任务：`POST /tasks/generate {novel,chapter,instruction}` → subprocess 跑 `novel.py generate N`，日志流 SSE 推给前端；revise/promo/outline 同理（任务锁：同一小说同时只跑一个 LLM 任务）
- `web/`：Vue3 + Vite + vue-router + pinia + Element Plus + axios
  - 页面：Dashboard（4 卷进度条/字数/伏笔回收率/读者评分趋势）、章节（列表+阅读+编辑+revise 入口）、生成控制台（指令输入+实时日志流+历史任务）、大纲/章名（阅读+编辑 outline.md）、知识库浏览器（人物/伏笔时间线/facts 搜索/lessons/style_hits）、风格工坊（banned_words.json 在线编辑+测试扫描）、宣传中心（promo 各类型一键生成+复制）
- 小说列表来自 `--list` 同源逻辑（扫 novels/ 目录）

## 2. Tech Stack

- Python 3.10+，现有 openai 依赖不变；新增 `fastapi`、`uvicorn`（唯一新增 pip 依赖）
- SQLite3（stdlib）；不引入 Chroma/向量库
- Node 22 / Vite 7 / Vue 3.5 / Element Plus（新增 npm 项目于 `web/`）

## 3. Commands

```bash
pip install fastapi uvicorn                          # 新增依赖
python novel.py --novel mirror-city db init          # 从 bible 导入生成 db/novel.db
python novel.py --novel mirror-city generate 5       # 行为不变，内部走 style_kit + DB
uvicorn server.app:app --port 11452 --reload          # 启动控制台后端
cd web && npm install && npm run dev                 # 前端 http://localhost:11451
cd web && npm run build                              # 产物可被 FastAPI 静态托管
python -m engine.style_kit.scanner 某草稿.txt         # 独立跑确定性扫描（调试用）
```

## 4. Project Structure

```
├── novel.py                  # +db 子命令；generate 流程接 scanner/DB（改动最小化）
├── engine/
│   ├── db.py                 # 新：schema+迁移+查询封装
│   └── style_kit/            # 新：banned_words.json / techniques.md / tomato_rules.md / scanner.py
├── server/                   # 新：FastAPI 后端（app.py, tasks.py）
├── web/                      # 新：Vue3 前端
├── novels/<name>/
│   ├── db/novel.db           # 新：运行时知识库
│   └── novel_prompts.json    # 改：注入正向技法+番茄规则
└── docs/specs/               # 本文档
```

## 5. Code Style

- Python：dataclass + type hints，stdlib 优先，函数短小；日志统一 `logging.getLogger("<module>")`
- SQL 只在 `engine/db.py` 内出现，Agent 通过函数调用访问
- Vue：`<script setup>` + Composition API；组件 kebab-case 文件名；API 层集中在 `web/src/api/`

示例（scanner 返回结构，同时是 DB 写入格式）：
```python
ScanResult(violations=[{"category": "词", "pattern": "然而", "count": 3, "locations": ["第2段", ...]}],
           metrics={"dialogue_ratio": 0.31, "avg_sentence_len": 14.2, "max_same_len_run": 4},
           passed=False)
```

## 6. Testing Strategy

- `tests/test_scanner.py`：禁用词命中/句长统计/对话占比的单元断言（pytest, stdlib 可跑）
- `tests/test_db.py`：init 幂等、伏笔状态流转、facts 检索
- 手工验收：用 mirror-city 跑 `generate 5`，对比 chapter_04 检查人味与钩子；前端走完"看板→生成→看日志→编辑章节"闭环

## 7. Boundaries

- **Always**：新表结构迁移幂等；bible JSON 双写不删除（旧命令仍可跑）；LLM 任务串行锁
- **Ask first**：新增 pip/npm 依赖超出上述清单；修改 Chapter 编号/卷结构等 config 语义
- **Never**：提交 .env/API key；绕过 scanner 直接发布 chapter md；删用户已生成章节

## 8. Success Criteria

1. 确定性 scanner 对旧章 chapter_03 扫描能复现 ≥ 已知违规（"然而/仿佛"类），新章节首稿扫描通过率高且人审盲测"像人"
2. `generate N` 后 `db/novel.db` 中该章 chapter_facts ≥ 5 条、伏笔 hinted_chs 更新、style_hits 有记录
3. Researcher 资料包不再整库塞 JSON：单章 prompt 体积下降 ≥30% 且事实一致性抽查通过
4. 前端 6 大页面可用，生成任务日志实时流式显示，章节编辑保存生效
5. 全部旧 CLI 命令行为不回退

## 9. Resolved Decisions (2026-09-13 用户确认)

- 单章字数**维持现状**（各场景 1500-2500，整章 2500-3500+），tomato_rules.md 不改数值长度指令，只管节奏与钩子
- style_kit 为引擎级共享，两本小说 prompts 同步升级
- Spec 已确认，按 A→B→C→D 4 阶段 11 任务实施
