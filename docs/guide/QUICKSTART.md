# 墨枢 快速启动

当前本地基线：Python 3.12、Node.js 20+、uv、SQLite；模型使用 LM Studio 或 OpenAI 兼容远程接口。Docker 不属于本地启动必需项。以下安装命令面向 macOS/Linux shell，每个终端先进入同一个 墨枢 仓库根目录。

## 首次安装

在仓库根目录安装后端依赖：

```bash
uv venv --python 3.12 backend/.venv
uv pip install --python backend/.venv/bin/python -r backend/requirements.txt
```

仅在没有 `.env` 时创建配置并替换随机 JWT 密钥；已有安装保留原配置：

```bash
python3 - <<'PYCONFIG'
from pathlib import Path
import secrets
p = Path('.env')
if not p.exists():
    lines = Path('.env.example').read_text().splitlines()
    lines = [line for line in lines if not line.startswith('SECRET_KEY=')]
    lines.append('SECRET_KEY=' + secrets.token_urlsafe(48))
    p.write_text('\n'.join(lines) + '\n')
    p.chmod(0o600)
    print('已创建本机配置，请按需编辑模型设置。')
else:
    print('已有 .env，保留现有配置。')
PYCONFIG
```

`SECRET_KEY` 必须为至少 32 字符的随机值，不能使用示例占位值。密钥仅保存在本机。

## 配置模型

默认模板指向 LM Studio 的 `http://127.0.0.1:1234/v1`。在 LM Studio 中加载聊天与 Embedding 模型，模型标识须与 [.env.example](.env.example) 对应。已安装 LM Studio CLI 时可执行：

```bash
~/.lmstudio/bin/lms server start --port 1234 --bind 127.0.0.1
~/.lmstudio/bin/lms load google/gemma-4-26b-a4b-qat --identifier google/gemma-4-26b-a4b-qat --context-length 32768 --parallel 2 -y
~/.lmstudio/bin/lms load text-embedding-nomic-embed-text-v1.5 --identifier text-embedding-nomic-embed-text-v1.5 -y
curl http://127.0.0.1:1234/v1/models
```

也可编辑项目根目录 `.env` 使用 DeepSeek 兼容接口，将模型名替换为账号实际可用的模型：

```dotenv
OPENAI_API_KEY=请填写本机密钥
OPENAI_API_BASE=https://api.deepseek.com/v1
OPENAI_MODEL_COMPLEX=deepseek-reasoner
OPENAI_MODEL_SIMPLE=deepseek-chat
EMBEDDING_ENABLED=false
```

模型名必须使用 DeepSeek 账号实际返回的 ID；如果 `/v1/models` 返回的名称不同，以返回值为准。DeepSeek Chat API 不提供本项目所需的 Embedding 时，先保持 `EMBEDDING_ENABLED=false`，或为 `EMBEDDING_API_BASE` / `EMBEDDING_MODEL` 单独配置本地或其他 OpenAI 兼容 Embedding 服务。

生成与 Embedding 分开配置；上例关闭 Embedding，RAG 明确降级。需要 RAG 时再配置可用的 Embedding 服务。不配置模型也可使用小说、正文与设定管理。

当前 墨枢 的 RAG 运行链是：LM Studio 的 Nomic Embedding（`/v1/embeddings`）→ 墨枢 内置持久化 Chroma（`backend/chroma_db`）→ 数据库 `ProjectionJob` 投影任务。它不依赖 Docker 中的 Qdrant；`docker-compose.yml` 里的 Qdrant、Redis、Neo4j 是尚未接入主链路的可选服务。

本机已有 Nomic 模型时，可这样启用：

```bash
~/.lmstudio/bin/lms server start --port 1234 --bind 127.0.0.1
~/.lmstudio/bin/lms load text-embedding-nomic-embed-text-v1.5 --identifier text-embedding-nomic-embed-text-v1.5 -y
```

然后在项目 `.env` 设置 `EMBEDDING_ENABLED=true`，重启后端。保存章节后，ProjectionWorker 会把已保存正文写入 Chroma；Embedding 不可用时任务会保留并按有限退避重试，不会伪装成已索引。

## 启动两个服务

终端一，从仓库根目录执行：

```bash
cd backend
.venv/bin/python init_db.py
.venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

终端二，同样从仓库根目录执行：

```bash
cd frontend
npm install
npm run dev
```

前端 [http://127.0.0.1:3000](http://127.0.0.1:3000)，API 文档 [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)，健康检查 [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)。前端 API 覆盖写入 `frontend/.env.local` 的 `NEXT_PUBLIC_API_BASE`，默认 `http://127.0.0.1:8000/api`。

注册后创建小说并进入工作区；正文、设定与持久对话的操作见 [使用指南](使用指南.md)。

## 已有安装升级与备份

保留现有 `.env`。停止应用写入，先使用 SQLite backup API 备份当前数据库；下例针对默认 `backend/novel.db`，自定义 `DATABASE_URL` 时应改成实际数据库路径：

```bash
python3 - <<'PYBACKUP'
import sqlite3
from datetime import datetime
from pathlib import Path
source = Path('backend/novel.db')
if not source.is_file():
    raise SystemExit('没有找到默认数据库，请核对 DATABASE_URL。')
Path('.Codex').mkdir(exist_ok=True)
target = Path('.Codex') / ('novel-backup-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.db')
with sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True) as src:
    with sqlite3.connect(target) as dst:
        src.backup(dst)
target.chmod(0o600)
print(target)
PYBACKUP
```

更新依赖后在 `backend` 执行 `.venv/bin/python init_db.py`。该入口处理空库、历史旧库与受 Alembic 管理的数据库。对话迁移 `f7a91b2c340d` 新增 `writing_turns`；记忆迁移 `a8d2e4f6b901` 新增 chapter_revisions / derived_jobs / chapter_digests；后续 `b9e3f5a7c012`、`c0f4a6b8d123`、`d1a5b7c9e234`、`e2b6c8d0f345` 依次增加来源清单、L2/L3 结构化状态、持久候选执行和 RAG 投影任务。只回填现有当前章节版本，不改作者正文。原文版本随每次保存增长，升级前确保本地磁盘可容纳快照。

迁移失败时保留错误日志并停止启动。恢复完整备份前先保存故障现场并停止所有连接；需要恢复匹配版本的代码和数据库。单独退回 `e6dc8b549c6d` 会移除对话表，不能当成保留对话的无损回滚。

## 检查与常见问题

后端在 `backend` 目录执行 `.venv/bin/python run_tests.py --mode all`。前端在 `frontend` 目录执行 `npm run lint`、`npm run typecheck`、`npm test`、`npm run build`。测试范围与 Node 25/26 的 Web Storage 处理见 [测试指南](../../backend/TESTING.md)。本机 SOCKS 代理导致 httpx 导入失败时，可用 `env -u ALL_PROXY -u all_proxy` 前缀运行后端测试。

- 模型不可用：检查服务、模型标识及对应 `.env` 字段；RAG 还需要独立可用的 Embedding。
- 保存返回 409：先在冲突弹窗对比并保留草稿，选择覆盖、采纳服务端或另存新章，避免直接刷新丢稿。
- 对话没有逐字输出：当前对话等待完整回复，这是现有协议；高级续写使用独立 SSE 链路。
- 旧记录没有被 AI 记住：当前历史注入有预算；有效前章简介已按预算注入对话与高级续写；当前最多最近 3 章，并非读过全书，完整召回见 [四层设计](../design/记忆分层设计.md)。

## 启用章节简介提取

1. 按上文停止写入、备份，然后在 backend 执行 `.venv/bin/python init_db.py`，升级到当前 Alembic head `e2b6c8d0f345`。此过程不调用模型、不创建旧章批量提取任务。
2. 默认 `MEMORY_WORKER_ENABLED=false`：新的非空正文保存会写入任务，但不执行模型。确认简单模型可用后，在有效的 `.env` 设置 `MEMORY_WORKER_ENABLED=true` 并重启后端，才会处理积压任务。关闭时改回 false 并重启；正在运行的租约留待再次启用后恢复。
3. 工作区右侧「工具 → 章节记忆」可查看原文历史、简介和出处。旧章需要点击「重建简介」，只处理服务端已保存原文；没有保存的编辑稿不会被暗中提交。
4. 默认单 worker 串行运行，轮询 2 秒、租约 420 秒、每轮最多 3 次尝试。网络失败有限退避；作者显式重建失败任务会重置本轮尝试次数。到期旧 worker 不能发布，仍可能发生上游重复调用。
5. 当前单段提取最多 20000 Unicode 字符；更长章节由有界分段任务合并，单段引用起止必须与原文完全吻合，任一段失败则不发布部分简介。

原文历史与自动简介目前只读，不提供一键回滚正文或自动确认物品状态。退回 `f7a91b2c340d` 会删除三张记忆表：必须先停 worker、导出新增历史与任务、备份，并使用兼容旧结构的代码；不能作为无损降级。正文数据库本身的备份恢复仍按上节执行。

## 对话参考简介升级

继续按“备份→init_db.py→启动服务”升级至当前 head `e2b6c8d0f345`。`b9e3f5a7c012` 只为对话增加可空来源清单，后续迁移增加 L2/L3、候选执行和持久投影任务；原问答不改、旧轮次不伪造来源。旧版无 Alembic 历史但已有 writing_turns 的库也由 init_db.py 补齐列。回退到 `a8d2e4f6b901` 会移除后续来源、结构化状态、候选和投影表，须先导出；不能视作无损回滚。

已存在的有效简介即使 worker 关闭仍可只读召回；只有生成新简介需要启用 worker。首章无前章简介、旧简介过期或简介存储不可用时，问答继续使用当前正文及作者设定，并在“本次参考简介”显示说明。旧对话无清单时不展示此区域。
