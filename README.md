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

# 当前 PowerShell 会话；也可写入系统环境变量
$env:DEEPSEEK_API_KEY = "sk-your-key"
```

AI 主题构思优先读取 `API_KEY`，未设置时读取 `DEEPSEEK_API_KEY`；接口地址优先读取 `API_BASE_URL`，其次为 `DEEPSEEK_BASE_URL`，默认 `https://api.deepseek.com/v1`。可通过 `THEME_MODEL` 单独指定构思模型，默认 `deepseek-chat`。

## 快速开始

项目不附带示例小说。请先通过 Web 或 CLI 新建独立工作区。

### 方式一：Web 控制台

```powershell
scripts\dev.cmd
```

打开前端 `http://localhost:11451`，点击“新建小说”，填写小说 ID、书名、章节数等信息。也可以在弹窗顶部输入可选灵感和题材偏好，点击“生成方案”获取 3 个 AI 主题构思；选择卡片只会把建议填入创建表单，不会立即创建小说，确认和修改后仍需点击“创建并进入”。后端 API 位于 `http://127.0.0.1:11452`，Vite 开发服务器会将 `/api` 请求代理到后端。

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
- **生成控制台**：运行大纲、章名、生成、修订、卷总结、知识库任务并查看实时日志
- **知识库**：管理人物、线索、伏笔、母题，检索跨章事实和教训
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
  config.py             本书配置
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
