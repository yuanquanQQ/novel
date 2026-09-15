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

打开前端 `http://localhost:11451`，点击“新建小说”，填写小说 ID、书名、章节数等信息。AI 构思必须先选择一个方向（悬疑推理、都市情感、科幻未来、奇幻冒险、历史权谋、成长热血、惊悚生存、自由创作），并选择频道（默认男频）、主角类型（默认男主角）和篇幅（默认长篇 200-400 章），再填写可选灵感和题材偏好并点击“生成方案”获取 3 个主题构思。后端会严格校验主角类型和章节范围，不符合要求的模型方案不会展示；选择卡片只会把建议填入创建表单，不会立即创建小说，确认和修改后仍需点击“创建并进入”。后端 API 位于 `http://127.0.0.1:11452`，Vite 开发服务器会将 `/api` 请求代理到后端。

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

其他命令包括 `summary <卷号>` 以及 `promo synopsis|teaser|tags|author|cover|character|scene`。运行 `python novel.py` 可查看完整帮助。

## Web 控制台

`scripts\dev.cmd` 同时启动：

- 前端：`http://localhost:11451`
- 后端：`http://127.0.0.1:11452`
- FastAPI 文档：`http://127.0.0.1:11452/docs`

控制台包含：

- **总览**：章节与分卷进度、字数、读者评分、知识库统计
- **大纲/章名**：编辑 `outline.md` 和章名
- **章节**：阅读、保存正文并立即重新执行风格扫描
- **生成控制台**：按固定流水线推进——①大纲 → ②章名 → ③逐章写作（单章 / 批量连写至第 N 章，≤20 章、失败即停）→ ④卷末总结（卷满自动解锁，含欠账卷检测）→ ⑤发布；实时日志、步骤进度、缺章提醒、单章修订入口，同书任务串行锁
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
  cache/                流水线上下文与进度
novel.py                CLI 入口
tests/                  unittest 测试
```

## 测试

```powershell
.venv\Scripts\python.exe -m unittest discover -v
```

## License

MIT
