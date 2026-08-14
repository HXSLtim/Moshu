# Nai：AI 辅助长篇小说创作系统

Nai 是一个作者主导的本地小说创作工具，提供章节管理、版本化保存、Story Bible 事实与事件账本、AI 续写、RAG 上下文检索、一致性检查和多维审核。

项目的核心原则是：**作者数据是唯一真源，AI 只提供候选内容；RAG、图谱和统计都是可重建的派生数据。** 详细设计见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 当前可用能力

- 用户注册、登录和小说所有权隔离。
- 小说、章节和角色基础管理。
- Story Bible 基础能力：事实账本与剧情事件 CRUD。
- 章节摘要分页、正文按需加载、服务端分配下一章编号。
- 章节乐观版本控制，避免迟到的自动保存覆盖新稿。
- 有界撤销历史、串行 latest-only 自动保存和可取消的 SSE 请求。
- LangGraph 三阶段生成工作流，带统一上下文预算和有限重试。
- Chroma 持久 RAG，按小说和章节范围过滤，支持覆盖更新和清理。
- 六维章节审核，限制并发；任一审核失败时不会误报“可发布”。
- Unified MCP 只公布真实实现的能力；未实现操作明确返回失败。

## 当前技术基线

后端：

- Python 3.12
- FastAPI、Pydantic 2、SQLAlchemy
- SQLite
- LangChain、LangGraph、LlamaIndex
- Chroma
- OpenAI 兼容模型接口（LM Studio 本地模型或 DeepSeek 远程模型）

前端：

- Next.js 15、React 19、TypeScript
- MUI 6、Emotion

PostgreSQL、Qdrant、Redis 和 Neo4j 仍属于可选演进方向。Docker Compose 中存在相关服务定义，不代表当前主链路已经依赖它们。

## 本机快速启动

### 1. 启动 LM Studio

本项目默认使用：

- 聊天模型：`google/gemma-4-26b-a4b-qat`
- Embedding：`text-embedding-nomic-embed-text-v1.5`

```bash
~/.lmstudio/bin/lms server start --port 1234 --bind 127.0.0.1
~/.lmstudio/bin/lms load google/gemma-4-26b-a4b-qat \
  --identifier google/gemma-4-26b-a4b-qat \
  --context-length 32768 --parallel 2 -y
~/.lmstudio/bin/lms load text-embedding-nomic-embed-text-v1.5 \
  --identifier text-embedding-nomic-embed-text-v1.5 -y
```

可用以下命令检查模型：

```bash
curl http://127.0.0.1:1234/v1/models
```

### 2. 启动后端

```bash
uv venv --python 3.12 backend/.venv
uv pip install --python backend/.venv/bin/python -r backend/requirements.txt

cp .env.example .env
python3 -c 'import secrets; print("SECRET_KEY=" + secrets.token_urlsafe(48))' >> .env

cd backend
.venv/bin/python init_db.py
.venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

后端不会提供 JWT 默认密钥；`SECRET_KEY` 缺失、少于 32 个字符或仍为示例占位值时会安全失败。测试进程使用独立的显式测试密钥。

不启动 LM Studio 时，小说和章节 CRUD 仍可使用；AI 与 RAG 会明确返回不可用或降级结果，而不是阻止应用启动。

也可以只把生成链路切换到 DeepSeek。项目已按 OpenAI 兼容协议验证 `deepseek-v4-pro`；真实密钥仅写入本机 `.env` 或进程环境，不能提交到仓库：

```dotenv
OPENAI_API_KEY=请填写本机密钥
OPENAI_API_BASE=https://api.deepseek.com/v1
OPENAI_MODEL_COMPLEX=deepseek-v4-pro
OPENAI_MODEL_SIMPLE=deepseek-v4-pro
```

这不会自动替换 Embedding 服务。LM Studio 关闭时，AI 生成仍可走 DeepSeek；建议同时设置 `EMBEDDING_ENABLED=false`，让 RAG 立即进入明确降级状态，不再探测已关闭的本地端口。

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev
```

访问地址：

- 前端：http://127.0.0.1:3000
- API 文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/api/health

环境变量模板见 [.env.example](.env.example)。默认配置已经指向本机 LM Studio、SQLite 和 Chroma；如需覆盖，复制为项目根目录 `.env`。

## 本地验证

后端：

```bash
cd backend
.venv/bin/python run_tests.py --mode all
```

前端：

```bash
cd frontend
npm run lint
npx tsc --noEmit --incremental false
npm run build
```

`run_tests.py` 会原样返回 pytest 的退出码，任何依赖、收集或断言失败都会使命令失败。

## 目录

```text
Nai/
├── backend/
│   ├── app/api/routes/       API 与权限边界
│   ├── app/crud/             数据访问
│   ├── app/models/           SQLAlchemy 与 Pydantic 模型
│   ├── app/services/         AI、RAG、一致性和审核服务
│   ├── migrations/           Alembic 迁移（结构演进的唯一入口）
│   └── tests/                自动化测试
├── frontend/
│   ├── app/                  Next.js 页面
│   ├── components/           UI 组件
│   ├── hooks/                保存、历史和交互状态
│   └── lib/                  API 与 SSE 客户端
├── ARCHITECTURE.md           架构原则与演进边界
├── REQUIREMENTS_ANALYSIS.md  需求分析与迭代排序
└── .Codex/                   本次上下文、操作与验证记录
```

## 已知边界

- 结构化 Story Bible 已落地事实与事件账本；仍需继续把 `Novel.worldview` 中的扁平文本迁移到地点、大纲等模型。角色已有独立管理，地点、大纲等模型尚未纳入当前能力。
- 当前响应后的 RAG 投影不是可恢复任务；生产部署应升级为数据库 outbox。
- 真正的模型 token 流仍受多 Agent 编排边界限制；客户端取消已经贯通，但最终正文主要在生成阶段完成后输出。
- `init_db.py` 已统一空库/旧库/已管理库三种路径，Alembic 是结构演进唯一入口；旧库一次性过渡时会补建缺失表并 `stamp head`，其列级差异（如旧 chapters 缺检查约束）由兼容补齐覆盖，PostgreSQL 上线前需验证迁移在该方言上的回滚与数据量压测。

## 项目状态

当前阶段：本地 Alpha，优先保证长篇写作的数据正确性、可恢复性和上下文边界；不把未实现能力标记为完成。
