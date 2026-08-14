# 快速启动

## 前置条件

- macOS/Linux 或 Windows
- Python 3.12
- Node.js 20 或更高版本
- LM Studio 本地模型，或 DeepSeek 兼容接口；仅使用小说管理时两者都可不配置

Docker 不是当前本地基线的必需条件。

## 1. 准备模型

在 LM Studio 中加载一个聊天模型和一个 embedding 模型，并在 `127.0.0.1:1234` 启动 OpenAI 兼容服务。

如果只想把生成链路切到 DeepSeek，可在项目根目录的本机 `.env` 中设置以下内容；密钥不能提交到仓库：

```dotenv
OPENAI_API_KEY=请填写本机密钥
OPENAI_API_BASE=https://api.deepseek.com/v1
OPENAI_MODEL_COMPLEX=deepseek-v4-pro
OPENAI_MODEL_SIMPLE=deepseek-v4-pro
EMBEDDING_ENABLED=false
```

生成模型和 Embedding 是独立配置。关闭 LM Studio 后，上述配置仍可生成正文，但 RAG 会明确进入不可用或降级状态。

本机可直接执行：

```bash
~/.lmstudio/bin/lms server start --port 1234 --bind 127.0.0.1
~/.lmstudio/bin/lms load google/gemma-4-26b-a4b-qat \
  --identifier google/gemma-4-26b-a4b-qat --context-length 32768 --parallel 2 -y
~/.lmstudio/bin/lms load text-embedding-nomic-embed-text-v1.5 \
  --identifier text-embedding-nomic-embed-text-v1.5 -y
curl http://127.0.0.1:1234/v1/models
```

## 2. 准备后端

在项目根目录执行：

```bash
uv venv --python 3.12 backend/.venv
uv pip install --python backend/.venv/bin/python -r backend/requirements.txt
```

复制配置模板，并生成只保存在本机的 JWT 随机密钥：

```bash
cp .env.example .env
python3 -c 'import secrets; print("SECRET_KEY=" + secrets.token_urlsafe(48))' >> .env
```

`SECRET_KEY` 缺失、少于 32 个字符或仍为示例占位值时，后端会拒绝启动。

初始化并启动：

```bash
cd backend
.venv/bin/python init_db.py
.venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

验证：

```bash
curl http://127.0.0.1:8000/api/health
```

## 3. 准备前端

另开终端：

```bash
cd frontend
npm install
npm run dev
```

打开 http://127.0.0.1:3000，先注册用户，再创建小说和章节。

## 4. 运行检查

```bash
cd backend
.venv/bin/python run_tests.py --mode all

cd ../frontend
npm run lint
npx tsc --noEmit --incremental false
npm run build
```

## 常见问题

### 后端提示模型不可用

检查 LM Studio 服务和模型标识：

```bash
~/.lmstudio/bin/lms server status
~/.lmstudio/bin/lms ps
curl http://127.0.0.1:1234/v1/models
```

### RAG 不返回结果

确认 embedding 模型已经加载，而不是只加载聊天模型。默认标识必须是：

```text
text-embedding-nomic-embed-text-v1.5
```

### 章节保存返回 409

这表示页面持有的章节版本已过期。重新加载章节后再保存，避免覆盖其他窗口或较新的自动保存结果。

### 需要 Docker 吗

本地开发不需要。只有在验证 PostgreSQL、Redis 或 Neo4j 等可选基础设施时才启动 Docker；不要同时维护两套未验证的数据主链路。
