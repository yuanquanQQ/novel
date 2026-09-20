# AI 长篇小说创作引擎

多小说隔离的中文小说创作工具，提供命令行与 Web 控制台。每部小说拥有独立的配置、Bible、章节、缓存和 SQLite 运行时知识库；共享引擎负责大纲、写作、审阅、风格扫描与知识归档。

## 环境要求

- Python 3.10+
- Node.js 18+（仅 Web 前端需要）
- 可用的 DeepSeek/OpenAI 兼容 API

```powershell
python -m pip install openai fastapi uvicorn
cd web
npm install
cd ..

```

新建小说后，复制该小说目录中的 `.env.example` 为 `.env`，再填写本书的 API 配置和模型安排：

```powershell
Copy-Item novels\my-story\.env.example novels\my-story\.env
```

每部小说的 `.env` 只在加载该小说的 `config.py` 时读取，不会污染其他小说。文件中的值优先于同名系统环境变量；未配置时使用模板中的默认模型。`API_KEY` 优先于 `DEEPSEEK_API_KEY`，接口地址 `API_BASE_URL` 优先于 `DEEPSEEK_BASE_URL`，默认地址为 `https://api.deepseek.com/v1`。`THEME_MODEL` 控制主题构思模型，默认 `deepseek-chat`；其余 `*_MODEL` 变量分别控制各 Agent。`.env` 含密钥，已被 git 忽略，不要提交。

**不必手动编辑 .env**：Web 控制台「新建小说」弹窗内置模型配置（快速：创作/推理两档 + 逐 Agent 覆盖），创建时直接写入本书 `.env`；已有小说在「模型配置」页随时查看、修改、测试连通性（保存即生效；旧版内嵌模型的小说会在首次保存时自动升级为 `.env` 驱动，原 `config.py` 备份为 `.bak`）。API Key 只写入本机 `.env`，任何接口都不会回传明文。

## 快速开始

项目不附带示例小说。请先通过 Web 或 CLI 新建独立工作区。

### 方式一：Web 控制台

```powershell
start.bat
```

双击 `start.bat` 会在同一窗口启动前后端，后端健康检查通过后才启动前端，不会弹出额外窗口；按 Ctrl+C 或关闭窗口会清理两个服务进程。也可以运行 `scripts\dev.cmd` 手动分别启动服务。

打开前端 `http://localhost:11451`，点击“新建小说”，填写小说 ID、书名、章节数等信息。AI 构思必须先选择一个方向（悬疑推理、都市情感、科幻未来、奇幻冒险、历史权谋、成长热血、惊悚生存、自由创作），并选择频道（默认男频）、主角类型（默认男主角）和篇幅（默认长篇 200-400 章），再填写可选灵感和题材偏好并点击“生成方案”获取 3 个主题构思。后端会严格校验主角类型和章节范围；模型返回不合格方案时，会把具体校验错误反馈给模型并自动重试，最多调用 3 轮，每轮仍要求返回 3 个全部合格的完整方案。选择卡片只会把建议填入创建表单，不会立即创建小说，确认和修改后仍需点击“创建并进入”。

新建弹窗会在浏览器 `localStorage` 中自动保存创建表单、主题构思条件与结果，以及除 API Key 外的模型配置；取消或刷新页面后再次打开可继续编辑。创建成功会自动删除草稿，也可点击“清空草稿”手动清除。API Key 始终只保存在当前页面内存中，绝不会写入浏览器草稿。后端 API 位于 `http://127.0.0.1:11452`，Vite 开发服务器会将 `/api` 请求代理到后端。

### 方式二：CLI

```powershell
python novel.py create --id my-story --title "我的小说"
python novel.py --novel my-story status
```

可在创建时补充参数：

```powershell
python novel.py create --id my-story --title "我的小说" `
  --chapters 120 --words 3000 --genre "悬疑" --description "一句话简介"
```

`id` 只能包含小写字母、数字和连字符。创建结果位于 `novels/my-story/`，并自动初始化 Bible 文件、章名占位和 `db/novel.db`，无需复制其他小说。

## 基本创作流程

```powershell
# 编辑 novels/my-story/bible/ 下的世界观、人物、线索等种子资料后同步知识库
python novel.py --novel my-story db init

# 生成大纲和章名（调用 LLM）
python novel.py --novel my-story outline
python novel.py --novel my-story titles

# 生成、扫描和修订章节
python novel.py --novel my-story generate 1
python novel.py --novel my-story scan 1
python novel.py --novel my-story revise 1 "加强冲突，减少说明性文字"

# 待人工修订队列：查看 → 人工修订后发布 → 丢弃
python novel.py --novel my-story pending
python novel.py --novel my-story publish 1
python novel.py --novel my-story discard 1

# 查看状态和知识库统计
python novel.py --novel my-story status
python novel.py --novel my-story db stats
```

常用查看命令：

```powershell
python novel.py --list
python novel.py --novel my-story view outline
python novel.py --novel my-story view titles
python novel.py --novel my-story view chapter 1
python novel.py --novel my-story view bible
```

其他命令包括 `pending`、`publish <章号>`、`discard <章号>`、`summary <卷号>` 以及 `promo synopsis|teaser|tags|author|cover|character|scene`。运行 `python novel.py` 可查看完整帮助。

## 待人工修订与定稿权

一章生成后要经历风格扫描 + 审阅 + 对话 + 连续性等闸门。**未通过全部闸门的章节不再硬失败、也不再自动定稿**：正文与质量诊断会转入本书 `revision/` 目录（“待人工修订”队列），不进入 `generated/`、不写入知识库。定稿权在人——作家在 Web 编辑器改完，点「发布」（或 CLI `publish N`）才运行归档管线，把修订稿正式写入 `generated/` 与知识库；不想要的待修订稿可直接丢弃（CLI `discard N`）。同一章号的待修订稿会覆盖列表中的旧发布稿，丢弃后旧稿重新可见。发布后 `revision/` 中该章文件自动清空。

- **`GATE_FAIL_MODE` 环境变量**控制闸门失败行为，三处生效：root `.env`（对所有小说生效）、单本 `.env`（`novels/<id>/.env`，优先级最高）、以及 `config.py` 字段。
  - `pending`（默认）：未过闸门 → 进待人工修订队列，退出码为 `2`；批量写作停止，任务标记 `needs_revision`，不继续编写后文。
  - `abort`：恢复旧版硬失败——抛错中断、整章不产出（兼容历史行为）。
- `revision/` 目录随新建小说自动创建（`generated/` 的兄弟目录），旧小说无需迁移；该目录参与备份/还原与下载导出。
- 每章的诊断文件 `revision/chapter_<N>.json` 记录失败场景列表（各场景重试次数、闸门通过情况、最佳得分）与合并稿最终扫描命中，供 Web 编辑器逐条展示。

## 连载编辑与知识一致性

- 场景字数预算合计等于本章目标；写作接收上一场正文尾部，只有末场负责章尾悬念。主角目标、主动选择、具体回报与下一步行动优先于重复铺气氛。
- 合并后必须经过整章编辑、对话、连续性与读者审阅；困惑、拖沓、续读不足会触发有限修订及复审。空响应或格式错误不会当作通过。
- 普通词语、长短句和口癖按语境审查，不设固定对话比例，不强制加入废话；确定性格式错误仍拦截。
- `revise N --prompt "修改要求"` 与已有章节的 `generate N --overwrite` 均保留旧定稿，把改稿放入待修订队列。旧章不再根据全书最新状态重新规划，避免未来经历倒灌。
- 发布前重新压缩实际保存的正文，只有正文中有证据的伏笔操作才入库。发布失败保留待修订稿，知识、缓存、正文通过事务回滚；成功提交后才清理待修订文件。
- 编辑已发布章节会使知识过期；已有摘要哈希与磁盘正文不符时也会阻止续写。请先重建，避免新版正文搭配旧摘要。

```powershell
python novel.py --novel my-story prepare
python novel.py --novel my-story rebuild
python novel.py --novel my-story recover
```

`prepare` 补充缺失的人物动机、底线、能力边界和声口，保留已填写字段。`rebuild` 按最终正文逐章重建知识，保留 `.history/` 快照，失败自动回滚；这两项通常会调用本书配置的模型。`recover` 仅在归档中断、存在事务日志时恢复到归档前快照，不调用模型。重建和恢复入口也位于生成控制台。

## 全项目写作与运行保护

以下机制由共享引擎执行，新书和已有小说均适用，不需要批量重写各书的提示词或正文。

- **连载创作规则**：`engine/style_kit/story_rules.md` 在加载规划、写作和审稿提示词时统一注入。按题材检查读者期待、可见回报、因果衔接、反派利益、成长依据和人物牵挂，并对照近期章节避免重复套路。已定稿事实优先于旧大纲；不强制每章胜利或固定节拍。各书自定义提示词保留不变。对白统一使用中文双引号“”，嵌套使用‘’。
- **人工设定优先**：通过 Web 人物、线索、伏笔表单或对应原始 JSON 编辑器保存的修改，另存于 `bible/author_overrides.json`，知识重建时回放。人物动机、声口、底线、能力边界等基础字段持续保护；地点、伤势等动态修改在指定章末（未指定时为最新定稿章，开书前为第 0 章）生效，允许后续剧情演变。人物修正同时同步数据库状态与故事记忆的同名字段及常见中英文别名；任意自定义语义不能自动识别。直接用外部编辑器改文件不生成编辑记录，重建仅额外保留现有人物的基础字段。
- **相关记忆检索**：按本章涉及的人物和事实、伏笔兑现时间、悬念积压时间选择上下文，不再只取人物表头部。原始记忆不因上下文限额被删除，不向旧章注入后文事实。
- **自动断点续写**：每完成一个场景及其摘要，原子保存检查点。任务中断后，以相同章号和要求重新生成，可复用已完成场景，仍执行最终整章审查。设定、前文、相关缓存、提示词、模型参数或引擎代码发生变化时不复用旧检查点；旧文件保留，成功发布后清理本次检查点。待修订章节仍须先定稿或丢弃，不能绕过队列。
- **跨进程写锁**：同一本书的 CLI 写作、Web 修改、知识事务共用系统文件锁，不同书可分别操作；进程异常退出后锁自动释放。锁文件位于 `novels/.locks/`，不要手工删除正在使用的锁文件。
- **用量与预算**：CLI 任务将模型名称、耗时、调用次数、服务方返回的 token 数写入 `cache/model_usage.jsonl`，不记录密钥、提示词或正文；服务方没返回的用量记为 `null`，不推算费用。单章任务默认最多 120 次请求（含失败重试）；大纲、章名、整书重建默认上限为 `max(120, 12 × 章数)`，重建按已有章节计算。根目录或本书 `.env` 可用 `MAX_MODEL_CALLS_PER_TASK=120` 设置明确的任务总上限，本书配置优先，显式值不再按章数放大。
- **备份空间**：连续知识快照中的未变文本可共享历史备份文件，不与正在使用的正文硬链接；不支持硬链接时自动复制。SQLite 仍用一致性全量备份，不自动删除旧快照。`.history/` 应视为只读，直接改动其中的硬链接文件会影响共享该文件的其他快照。

这些检查降低丢稿、知识冲突和重复写作的风险，不代表模型审稿等同于真实读者判断。模型质量和实际连载体验仍需通过新章节试写与人工审稿评估。

## Web 控制台

`scripts\dev.cmd` 同时启动：

- 前端：`http://localhost:11451`
- 后端：`http://127.0.0.1:11452`
- FastAPI 文档：`http://127.0.0.1:11452/docs`

控制台包含：

- **总览**：章节与分卷进度、字数、读者评分、知识库统计、待人工修订计数；种子数据（人物/线索/母题）未补充时给出提示并跳转知识库
- **大纲/章名**：编辑 `outline.md` 和章名
- **章节**：阅读、保存正文并立即重新执行风格扫描；「待修订」筛选与徽标展示未通过全部闸门的章节，点开即见质量诊断面板（失败场景的闸门明细 + 合并稿扫描命中），可直接编辑、保存到待修订、发布（任务日志实时滚动）或丢弃
- **生成控制台**：按固定流水线推进——①大纲 → ②章名 → ③逐章写作（单章 / 批量连写至第 N 章，≤20 章、失败即停）→ ④卷末总结（卷满自动解锁，含欠账卷检测）→ ⑤发布；实时日志、步骤进度、缺章提醒、单章修订入口，同书任务串行锁；有待修订章节时顶部横幅提示并一键跳转处理
- **知识库**：管理人物、线索、伏笔、母题，检索跨章事实和教训
- **模型配置**：查看/修改本书 API Key（脱敏）、Base URL 和 10 个 Agent 的模型，一键连通性测试；新建小说弹窗内也能直接配置
- **风格工坊**：编辑共享禁用词规则并试扫文本

单独启动服务：

```powershell
python -m uvicorn server.app:app --host 127.0.0.1 --port 11452 --reload
cd web
npm run dev -- --port 11451
```

构建前端：

```powershell
cd web
npm run build
```

## 真实知识库如何工作

每部小说的运行时知识库是 `novels/<id>/db/novel.db`，不是演示数据。它记录人物状态、线索、伏笔生命周期、跨章事实、风格命中、创作教训和章节成绩。

- **直接在 Web 编辑**：进入“知识库”，可新增或修改人物、线索、伏笔和母题；人物、线索、伏笔会直接写入 SQLite，母题通过 Bible 文件保存后同步。
- **编辑种子文件**：在“知识库 → 原始文件”修改 `characters.json`、`clues.json`、`motif_bank.json` 等，保存时自动校验 JSON/JSONL 并同步数据库。
- **手动同步**：点击“同步原始文件”，或运行 `python novel.py --novel my-story db init`。同步是幂等的，不需要删除数据库。
- **自动积累**：章节生成与保存过程中会写入事实、状态、风格命中和章节日志，后续章节的 Researcher 会查询这些运行时记录。

查看统计：

```powershell
python novel.py --novel my-story db stats
```

## 项目结构

```text
engine/                 共享创作引擎、Agent、SQLite 与风格扫描器
server/                 FastAPI REST/SSE 后端
web/                    Vue 3 + Vite 控制台
novels/<id>/
  config.py             本书配置（从同目录 .env 读取）
  .env.example          API 与 Agent 模型配置示例
  .env                  本机配置，不提交
  novel_prompts.json    本书提示词
  bible/                世界观、人物、线索、大纲、章名等种子文件
  db/novel.db           本书运行时知识库
  generated/            已生成章节
  revision/             待人工修订章节（未过闸门）+ 质量诊断
  cache/                流水线上下文与进度
novel.py                CLI 入口
tests/                  unittest 测试
```

## 测试

```powershell
.venv\Scripts\python.exe -m unittest discover -v
```

隔离任务历史的离线回归，以及前端发布顺序测试：

```powershell
.venv\Scripts\python.exe -X utf8 scripts/check_suite.py
cd web
node --test tests/publishPending.test.js
npm run build
```

`powershell -ExecutionPolicy Bypass -File scripts/start_preview.ps1` 启动独立预览（前端 11453，后端 11454），不影响常规开发端口；端口占用时拒绝启动。进程号会打印，日志在 `runtime/preview-*.log`。

## License

MIT
