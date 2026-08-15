# 后端测试说明

## 测试基线

- 位置:`backend/tests/`,22 个测试文件,193 个收集项(191 通过、2 个真实模型集成项按标记跳过),当前全绿。
- 框架:pytest + pytest-asyncio + FastAPI TestClient,`pytest.ini` 已启用 `asyncio_mode = auto`、`--strict-markers`,并默认附带 `--cov=app` 覆盖率统计(HTML 报告输出到 `htmlcov/`)。
- 测试不依赖任何真实外部服务:模型调用在夹具中打桩,数据库使用覆盖注入。

## 运行方式

统一通过 `run_tests.py` 执行,它原样传递 pytest 退出码:

```bash
cd backend
.venv/bin/python run_tests.py --mode all         # 全量(默认)
.venv/bin/python run_tests.py --mode unit        # 排除 integration 标记
.venv/bin/python run_tests.py --mode integration # 仅集成标记,需 --run-integration 显式放行
.venv/bin/python run_tests.py --mode coverage    # 额外生成 htmlcov 报告
.venv/bin/python run_tests.py --file test_rag_service.py  # 单文件
```

`integration` 标记的测试允许访问真实外部服务,默认不会在 unit/all 模式下误跑。

## 测试主题索引

| 主题 | 文件 | 覆盖点 |
|---|---|---|
| 章节 CRUD 与并发 | `test_chapter_management.py`、`test_auto_chapter.py` | 服务端分配章号、`(novel_id, chapter_number)` 唯一冲突、`expected_version` 乐观锁 409 |
| 基础 API | `test_api.py` | 认证、小说所有权隔离、常规 CRUD 流程 |
| AI 路由守卫 | `test_ai_route_guards.py` | AI 端点鉴权、模型不可用时的明确降级而非崩溃 |
| 生成契约 | `test_generation_consistency_contract.py`、`test_agent_retry.py` | 生成结果结构、一致性状态、重试上限 |
| 上下文预算 | `test_context_budget.py`、`test_schema_input_budgets.py` | 各类输入截断边界、schema 字段上限 |
| 字数统计 | `test_text_stats.py` | 非空白 Unicode 计数、组合标记与 ZWJ 忽略、章节 CRUD 写入 |
| 审核 | `test_review_fail_closed.py` | 任一审核失败时不得报告"可发布" |
| RAG | `test_rag_service.py` | 投影真源、覆盖更新、按范围过滤、删除清理 |
| 一致性 | `test_consistency_service.py` | 规则校验、关系抽取、降级行为 |
| MCP | `test_unified_mcp_service.py`、`test_mcp_audit_service.py`、`test_character_mcp_route.py` | 能力公布与真实实现一致、审计落库、未实现操作返回失败 |
| Story Bible | `test_story_bible.py`、`test_story_bible_generation_context.py` | 事实/事件 CRUD、退役状态流转、写入预算、跨小说 404 隔离、生成上下文过滤与注入 |
| 基础设施 | `test_sqlite_compat.py`、`test_security_config.py`、`test_run_tests_script.py` | 旧库幂等迁移、SECRET_KEY 安全校验、退出码传播 |
| 数据库初始化与并发 | `test_init_db.py`、`test_sqlite_pragmas.py` | 空库/旧库/已管理库三条 Alembic 升级路径、SQLite WAL 与写锁等待 |

## 夹具与环境

- `client`:覆盖 `get_db` 与用户依赖,隔离真实数据库;测试用 `SECRET_KEY` 由 conftest 显式注入。
- `mock_openai_response`:模型调用打桩,不访问 LM Studio/DeepSeek。
- **本机代理坑**:若环境设置了 `all_proxy=socks5://...`(如 Clash),openai/httpx 会在导入阶段抛 `ImportError: socksio`。运行测试前执行:

```bash
unset ALL_PROXY all_proxy
```

## 前端测试

```bash
cd frontend
npm run test        # vitest run
npm run lint        # eslint .
npm run typecheck   # tsc --noEmit
```

覆盖保存协调(`useChapterSave`)、编辑历史、API/SSE 客户端与工作台导航。
