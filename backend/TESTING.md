# 后端测试说明

## 测试基线

- 位置:`backend/tests/`,当前最终全量为 544 通过、2 个真实模型集成项按标记跳过；测试文件数量随功能增长,当前全绿。
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
| 整本导出 | `test_chapter_management.py` | 超过 100 章不漏章、按章号排序、空小说、跨作者 404 隔离 |
| 持久创作对话 | `test_writing_chat.py` | 历史恢复与模型上下文、幂等重传、章节/作者隔离、失败保留、停止与迟到回复、过期恢复、分页、级联删除和完成/取消竞争、截断失败不进入历史上下文、独立超时原因 |
| 基础 API | `test_api.py` | 认证、小说所有权隔离、常规 CRUD 流程 |
| AI 路由守卫 | `test_ai_route_guards.py` | AI 端点鉴权、模型不可用时的明确降级而非崩溃 |
| AI Prompt 契约 | `test_ai_prompt_contracts.py` | 六维审核的正文/前文花括号原样传递、重试诊断数据边界、首章禁止无界历史检索、六维审核拒绝传输被截断的有效 JSON |
| 生成契约 | `test_generation_consistency_contract.py`、`test_agent_retry.py` | 生成结果结构、一致性状态、重试上限 |
| 共享 L1 上下文 | `test_context_builder.py`、`test_generation_context_pack.py`、`test_writing_context.py` | 章节/版本/配方/来源核验、有界召回、存储降级、真实模型消息与来源清单一致、历史清单不随改稿变动 |
| 对话来源迁移 | `test_context_manifest_migration.py` | 可空列升级/回退、旧轮次不伪造来源、无迁移历史旧表补列 |
| 原文与持久任务 | `test_memory_models.py`、`test_chapter_memory_api.py` | 三表迁移/回填、正文保留、整体事务回滚、版本/任务幂等、权限与生命周期、只读来源端到端 |
| 简介执行 | `test_digest_extractor.py`、`test_memory_worker.py` | 严格提取及引用、租约恢复、双线程竞争、旧版本/旧token/取消不发布、有界重试、事件循环公平性 |
| 模型运行契约 | `test_model_result.py`、`test_model_provider.py`、`test_generation_model_contract.py` | 提供方完成原因冲突、截断/工具输出拒绝、真实用量保留、集中连接参数、生成/续写/一致性默认未知故事日 |
| 上下文预算 | `test_context_budget.py`、`test_schema_input_budgets.py` | 各类输入截断边界、schema 字段上限 |
| 字数统计 | `test_text_stats.py` | 非空白 Unicode 计数、组合标记与 ZWJ 忽略、章节 CRUD 写入 |
| 审核 | `test_review_fail_closed.py` | 任一审核失败时不得报告"可发布" |
| RAG | `test_rag_service.py`、`test_projection_jobs.py` | 投影真源、覆盖更新、按范围过滤、删除清理、持久任务恢复 |
| 一致性 | `test_consistency_service.py` | 规则校验、关系抽取、缺少参考时明确跳过 |
| MCP | `test_unified_mcp_service.py`、`test_mcp_audit_service.py`、`test_character_mcp_route.py` | 能力公布与真实实现一致、审计落库、未实现操作返回失败 |
| Story Bible | `test_story_bible.py`、`test_story_bible_generation_context.py` | 事实/事件 CRUD、退役状态流转、写入预算、跨小说 404 隔离、小说删除级联及主键复用隔离、历史时点事实和计划事件过滤 |
| 基础设施 | `test_sqlite_compat.py`、`test_security_config.py`、`test_run_tests_script.py` | 旧库幂等迁移、SECRET_KEY 安全校验、退出码传播 |
| 数据库初始化与并发 | `test_init_db.py`、`test_sqlite_pragmas.py` | 空库/旧库/已管理库三条 Alembic 升级路径、SQLite WAL 与写锁等待 |

## 夹具与环境

- `client`:覆盖 `get_db` 与用户依赖,隔离真实数据库;测试用 `SECRET_KEY` 由 conftest 显式注入。
- `mock_openai_response`:模型调用打桩,不访问 LM Studio/DeepSeek。
- **本机代理坑**:优先用 `./run_tests.sh`(它统一清理全部 8 个代理变量)。手工命令与完整原因见
  [AGENTS.md](../AGENTS.md) 的「验证」节 —— 只 `unset ALL_PROXY all_proxy` **不够**:
  `NO_PROXY` 里的 `[::1]` 会让 httpx 在**导入期**抛 `InvalidURL: Invalid port: ':1]'`,
  崩在 collection 阶段且报错看起来与代理无关。

## 已知陷阱:测试假绿(`SessionLocal()` 绕过 DI)

夹具用 `app.dependency_overrides[get_db]` 换成隔离库,但业务代码里有直接建会话的地方 ——
这些读写**落到真实库**,而断言查的是隔离库,于是测试永远是绿的。

```bash
grep -rn "SessionLocal()" app --include=*.py | wc -l   # 2026-09 复核:10 处
```

集中在 `app/services/agent_tools.py`、`agent_service.py`,以及 `app/db/base.py`、`rag_service.py`。
怀疑某条断言是假绿时,先确认读写的归属库:当时用于判断的库内基线是 `writing_turns` 8 条、
`novels` 4 条(重建测试库后会变,重跑取当前值)。归属对不上就是绕过了 DI,不要先改断言。

另注:`conftest.py` 同时覆盖了 `get_db` 与 `get_current_user`,因此 **`security.py` 与
`/api/auth` 路径是零覆盖** —— 真实 token 解析、过期与越权分支在测试里跑不到,
需要单独写不注入 override 的用例。

## 前端测试

```bash
cd frontend
npm run test        # vitest run
npm run lint        # eslint .
npm run typecheck   # tsc --noEmit
```

最终 26 个测试文件、115 项通过，覆盖保存协调(`useChapterSave`)、编辑历史、API/SSE 客户端、工作台导航、设定账本表单与分页，新保存失败时保留草稿备份，以及改写快照、持久对话恢复、网络失败草稿保留和迟到响应保护。Node 25/26 使用 `NODE_OPTIONS=--no-experimental-webstorage npm test` 避免原生 Web Storage 与 jsdom 冲突。

M1 采用隔离 SQLite 与模型替身验证；真实 Embedding/Chroma 链路另有隔离 smoke，不访问作者真实数据库或真实模型。真实库启用、长篇提取质量及共享召回为单独验收项。前端新增章节记忆的展开请求、保存版本刷新、切章取消与迟到响应保护、只读历史及来源查看回归。

共享上下文批次增加只读来源清单的前端测试，覆盖历史恢复、版本身份核验、404 保留回复、取消/切小说迟到保护。对应全量日志 `.Codex/context-pack-backend.log`、`.Codex/context-pack-frontend.log`。固定质量样例在 evaluations/，尚未执行真实模型评测。
