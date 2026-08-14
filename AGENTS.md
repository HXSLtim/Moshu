# Nai 开发规范

本文件约束仓库内全部开发与文档工作。目标:输出与代码库现状一致、可本地验证、可审计。

## 项目事实(先读这些,再动手)

- 定位与架构原则:`README.md`、`ARCHITECTURE.md`
- API 契约:`API对接文档.md`;测试基线:`backend/TESTING.md`
- 历史归档(不代表现状):`PRIORITY_PLAN.md`、`FEATURE_EXTENSION_TASKS.md`

## 语言规范

- 所有 AI 回复、文档、注释、提交信息、测试描述一律使用**简体中文**。
- 唯一例外:代码标识符遵循项目既有英文命名约定。
- 注释描述意图、约束与使用方式,不写"修改说明"式注释。

## 编码前上下文检索

1. 定位相似实现:用 grep/glob 找到同类功能的既有文件,**至少深读 3 个**。
2. 确认可复用组件:优先复用 `app/services/`、`app/crud/`、`frontend/hooks/`、`frontend/lib/` 既有模块,禁止重复造轮子。
3. 确认约定:命名、文件组织、导入顺序、测试编排,与新实现所在目录的既有代码保持一致。
4. 跨模块或超过 5 个子任务的工作,先建任务分解再动手。

## 架构与实现标准

- 遵循 `ARCHITECTURE.md` 四原则:数据库唯一真源、派生数据可重建、AI 操作可审阅、能力必须诚实。
- 未实现的功能明确返回不可用,禁止占位符、假数据、伪装成功的固定分数。
- 破坏性改动不做向后兼容,但必须提供迁移步骤或回滚方案(`backend/app/db/sqlite_compat.py` 是范例)。
- 所有 AI 调用经过统一上下文预算(`app/services/context_budget.py`),不得绕过预算自行拼接全文。
- SOLID、DRY、单一职责;禁止过早抽象(重复三次以上再通用化)。

## 验证(强制)

- 后端:`cd backend && .venv/bin/python run_tests.py --mode all`,退出码必须为 0。
- 前端:`npm run lint && npm run typecheck && npm run test`。
- 验证失败禁止提交;无法验证的部分必须在交付说明中列为风险并给出补验计划。
- 本机若开 Clash(socks5 代理),先 `unset ALL_PROXY all_proxy` 再跑测试,否则 openai/httpx 导入即崩。

## 工作留痕

任务过程文件写入项目本地 `.Codex/` 目录(已 git ignore,不入库):

```
.Codex/
├── context-summary-<任务名>.md   ← 编码前上下文摘要
├── operations-log.md             ← 决策与操作记录
└── verification-report.md        ← 验证结果
```
