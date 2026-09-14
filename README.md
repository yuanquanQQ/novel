# AI 长篇小说创作引擎

**10 Agent 协作 · 模块化 · 多小说支持 · 全流程覆盖**

从大纲规划、逐章撰写、质量审阅到平台发布宣传，一条命令搞定。

---

## 快速开始

```bash
# 1. 安装
pip install openai

# 2. 配置 API Key
[Environment]::SetEnvironmentVariable("DEEPSEEK_API_KEY", "sk-your-key", "User")

# 3. 进入项目
cd mirror-city-novel

# 4. 生成全书大纲（分卷生成→bible/outline.md）
python novel.py --novel mirror-city outline

# 5. 提取章名（从大纲自动解析→bible/chapter_titles.json）
python novel.py --novel mirror-city titles

# 6. 初始化本书数据库（人物/伏笔/事实/教训 → db/novel.db）
python novel.py --novel mirror-city db init

# 7. 逐章生成（自动经过 风格扫描器→LLM语义审→声纹审计 三道闸）
python novel.py --novel mirror-city generate 1

# 8. Web 控制台（推荐：看板/章节编辑/一键生成+实时日志/知识库浏览）
pip install fastapi uvicorn
scripts\dev.cmd     # 后端 http://127.0.0.1:11452 · 前端 http://localhost:11451
```

---

## 番茄人味体系（v2 新增）

```
engine/style_kit/          # 全局共享风格库（改一处=所有小说生效）
├── banned_words.json      # 硬禁用词61 + 软禁词阈值 + 10条AI句式 regex + 模板道具表（前端可编辑）
├── techniques.md          # 15条正向人味技法（情绪体感化/私人细节/句式情绪同步/干扰项/主角犯错…）
├── tomato_rules.md        # 番茄连载纪律（「」对话/章末硬钩/800字一推进/手机段落…）
└── scanner.py             # 确定性扫描器：零成本拦机械违规，先于LLM审阅执行
```

- **三道闸**：`scanner`（代码扫描，禁用词/破折号/半角引号/省略号/段首重复，命中必打回重写）→ LLM 语义审（只管扫描器看不了的：叙事模板/信息直塞/声口/衔接）→ 对话声纹审计
- 提示词内禁用词与 scanner **同一数据源**（`[STYLE_FORBIDDEN]` token 自动注入），永不同步失败

## 每小说运行时数据库（v2 新增）

`novels/<name>/db/novel.db`（SQLite）：人物状态时间线、伏笔生命周期（埋设→每次触碰→回收）、跨章原子事实、风格惯性命中统计、人类修改教训、章节成绩单。Researcher 按本章场景人物**查询驱动**注入资料包，替代整库 JSON 截断；`generate` 后 Archivist 自动双写。

## Web 控制台（v2 新增）

Vue3 + Element Plus，`web/` 目录；后端 FastAPI（`server/`）：

| 页面 | 功能 |
|------|------|
| 总览 | 4卷进度/字数/伏笔回收/读者评分趋势/风格惯性Top |
| 大纲章名 | outline.md 在线编辑、章名双击改 |
| 章节 | 阅读/编辑/保存即复检扫描、扫描报告侧栏 |
| 控制台 | generate/revise/summary/outline 一键跑，SSE 实时日志流，同书任务串行锁 |
| 知识库 | 人物近况时间线、伏笔状态分桶（到期未收/已遗忘）、事实检索、Bible 文件编辑 |
| 风格工坊 | banned_words.json 在线编辑实时生效、扫描器实验室 |

```bash
# 生产：前端构建产物可直接被 FastAPI/任意静态服务器托管
cd web && npm install && npm run dev      # 开发
cd web && npm run build                   # 产物在 web/dist
```

---

## 完整命令参考

所有命令通过 `novel.py` 统一入口，`--novel` 指定小说。

### 规划阶段

| 命令 | 说明 |
|------|------|
| `outline` | 分卷生成全书大纲 → `bible/outline.md`（每章含剧情+功能+伏笔标签） |
| `outline -p "要求"` | 带修改指令重新生成大纲 |
| `titles` | 从大纲自动解析章名 → `bible/chapter_titles.json` |
| `titles -p "要求"` | LLM 辅助生成/补全章名 |

```bash
python novel.py --novel mirror-city outline
python novel.py --novel mirror-city titles
```

### 写作阶段

| 命令 | 说明 |
|------|------|
| `generate N` | 生成第N章（标题自动锁定） |
| `generate N -p "指令"` | 带创作指令生成 |
| `revise N "要求"` | 修订第N章 |
| `summary V` | 生成第V卷卷末总结 |
| `summary V -r "要求"` | 修订卷末总结 |

```bash
python novel.py --novel mirror-city generate 1
python novel.py --novel mirror-city generate 2 -p "这章要有打斗场面"
python novel.py --novel mirror-city revise 3 "节奏太快，删减环境描写"
python novel.py --novel mirror-city summary 1
```

### 查看阶段

| 命令 | 说明 |
|------|------|
| `status` | 创作进度（字数、百分比、伏笔回收率） |
| `view outline` | 查看全书大纲 |
| `view titles` | 查看全部章名 |
| `view chapter N` | 查看第N章正文 |
| `view bible` | 查看知识库文件状态 |
| `scan N` | 对第N章跑确定性风格扫描（不花API钱，看AI痕迹基线） |
| `db init` / `db stats` | 初始化本书 SQLite 知识库 / 查看统计 |
| `--list` | 列出所有可用小说 |

```bash
python novel.py --novel mirror-city status
python novel.py --novel mirror-city view outline
python novel.py --novel mirror-city view titles
python novel.py --novel mirror-city view chapter 1
python novel.py --novel mirror-city view bible
python novel.py --list
```

### 宣传阶段（Marketer Agent）

| 命令 | 说明 |
|------|------|
| `promo synopsis` | 小说简介（200字，平台展示） |
| `promo teaser N` | 第N章推荐语（50字） |
| `promo tags` | 平台标签（8-12个） |
| `promo author` | 作者的话 |
| `promo cover` | 封面图视觉描述（3套方案） |
| `promo character 人名` | 人物立绘视觉描述 |
| `promo scene N` | 第N章场景插图视觉描述 |

```bash
python novel.py --novel mirror-city promo synopsis
python novel.py --novel mirror-city promo teaser 3
python novel.py --novel mirror-city promo tags
python novel.py --novel mirror-city promo author
python novel.py --novel mirror-city promo cover
python novel.py --novel mirror-city promo character 林泽
python novel.py --novel mirror-city promo scene 1
```

---

## 完整创作流程

```
① outline → 审阅 bible/outline.md（可直接编辑修改）
② titles  → 审阅 bible/chapter_titles.json
③ generate 1 → 读 → 不满意 revise 1 "要求" → 满意
④ generate 2 → 读 → revise → ...
⑤ generate 3 → ...
   ...
⑥ summary 1（第一卷结束）
⑦ 重复 ③-⑥ 直到 210 章
⑧ promo synopsis / tags / cover → 发布
```

---

## 10 Agent 架构

```
                        ┌─────────────┐
                        │   novel.py  │
                        └──────┬──────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        ▼                      ▼                      ▼
   规划阶段               写作流水线               宣传阶段
   Planner              ┌──────────┐              Marketer
   (outline/titles)     │ ①Planner │              文字/生图
                        │ ②Steward │
                        │ ③Researcher│
                        │ ④Writer   │
                        │ ⑤Reviewer │  ← 每场景重试
                        │ ⑥Auditor  │
                        │ ⑦Keeper   │
                        │ ⑧Reader   │
                        │ ⑨Archivist│
                        └──────────┘
```

| # | Agent | 时机 | 模型 | 职责 |
|---|-------|------|------|------|
| ① | Planner | 每章开始 | reasoner T=0.6 | 场景大纲+情绪弧线+伏笔操作+明暗钩子 |
| ② | Steward | Planner后 | reasoner T=0.6 | 伏笔生命周期：过期/重复/遗忘风险 |
| ③ | Researcher | Steward后 | reasoner T=0.15 | 从Bible检索人物/线索/母题/伏笔 |
| ④ | Writer | 每场景 | chat T=0.9 | 1500-2500字正文，7条铁律 |
| ⑤ | Reviewer | Writer后 | chat T=0.15 | AI高频词/视角/声纹/衔接/字数 |
| ⑥ | Auditor | Reviewer后 | chat T=0.15 | 对话专项：声纹匹配/信息dump/区分度 |
| ⑦ | Keeper | 场景通过后 | chat T=0.15 | 300字三模块记忆压缩 |
| ⑧ | Reader | 全章合并后 | chat T=0.3 | 模拟读者：吸引力/困惑点/续读意愿 |
| ⑨ | Archivist | Reader后 | chat T=0.15 | 保存章节+更新Bible+伏笔回收 |
| ⑩ | Marketer | 手动调用 | chat T=0.7 | 简介/推荐语/标签/生图提示词 |

---

## 项目结构

```
mirror-city-novel/
├── novel.py                      # ★ 统一入口（含 scan / db 子命令）
│
├── engine/                       # 共享引擎（所有小说共用，不需修改）
│   ├── settings.py               # set_novel() 动态切换
│   ├── llm_client.py             # API调用+重试+JSON修复
│   ├── prompts_loader.py         # 提示词加载 + [STYLE_*] 共享规则注入
│   ├── db.py                     # SQLite 运行时知识库（人物/伏笔/事实/教训/命中）
│   ├── style_kit/                # 全局人味规则库（番茄向）
│   │   ├── banned_words.json     # 禁用词/句式/模板道具（scanner与提示词同源）
│   │   ├── techniques.md         # 15条正向人味技法
│   │   ├── tomato_rules.md       # 番茄连载纪律
│   │   └── scanner.py            # 确定性AI痕迹扫描器
│   └── agents/                   # 10个Agent
│
├── server/                       # FastAPI 控制台后端（REST + SSE任务流）
├── web/                          # Vue3 + Element Plus 前端（vite代理→11452）
├── tests/                        # scanner / db / server API 单元测试（25个）
│
└── novels/                       # 每本小说独立目录
    └── mirror-city/              # 镜影迷城（210章4卷）
        ├── config.py             # 书名/卷数/模型参数
        ├── novel_prompts.json    # 全部提示词（含[STYLE_*]占位）
        ├── bible/                # 出厂设定（世界观/人物/线索/母题/大纲/章名）
        ├── db/novel.db           # ★ 运行时知识库（随章节生长）
        ├── generated/            # 输出章节
        └── cache/                # Keeper快照+进度
```

---

## 开启下一本小说

```bash
# 复制 → 改配置 → 改提示词 → 写知识库 → 运行
cp -r novels/mirror-city novels/新书名
# 编辑 novels/新书名/config.py → story_title, volume_config
# 编辑 novels/新书名/novel_prompts.json → 世界观引用
# 编辑 novels/新书名/bible/ → 世界观/人物/线索/母题

python novel.py --novel 新书名 outline
python novel.py --novel 新书名 titles
python novel.py --novel 新书名 generate 1
```

---

## 当前项目：镜影迷城

| 卷 | 名称 | 章节 | 核心情绪 |
|----|------|------|----------|
| 一 | 镜影初醒 | 1-50 | 迷茫、恐惧、好奇 |
| 二 | 影潮涌动 | 51-110 | 紧张、背叛、羁绊加深 |
| 三 | 镜界裂痕 | 111-160 | 震撼、绝望、希望交织 |
| 四 | 镜我归一 | 161-210 | 燃、释怀、温暖 |

## License

MIT
