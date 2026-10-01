# Nai 开发规范

本文件约束仓库内全部开发与文档工作。目标:输出与代码库现状一致、可本地验证、可审计。

## 项目事实(先读这些,再动手)

- 定位与架构原则:`README.md`、`ARCHITECTURE.md`,文档索引:`docs/README.md`
- API 契约:`docs/guide/API对接文档.md`;测试基线:`backend/TESTING.md`
- 历史归档(不代表现状):`docs/plan/PRIORITY_PLAN.md`、`docs/plan/FEATURE_EXTENSION_TASKS.md`

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

- 后端:`cd backend && ./run_tests.sh --mode all`(或 `bash run_tests.sh --mode all`),退出码必须为 0。
  该脚本自动清理代理变量,等价于下方的手工命令。
- 前端:`npm run lint && npm run typecheck && npm run test`。
- 真实模型冒烟(按需手动,不进入 pytest 基线,会真实调用并计费):
  `cd backend && ./run_smoke.sh`。验证对话 Agent 的工具调用参数链路端到端完好。
- 验证失败禁止提交;无法验证的部分必须在交付说明中列为风险并给出补验计划。
- 环境坑(实测):本机开着 Clash 时只 `unset ALL_PROXY all_proxy` **不够**(只用这两个清过的命令
  仍会崩)。`NO_PROXY` 里的 `[::1]` 会让 httpx 在**导入期**抛 `InvalidURL: Invalid port: ':1]'`,
  测试在 collection 阶段就崩,报错看起来与代理无关。必须清掉全部 8 个代理变量:

  ```bash
  cd backend && env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u http_proxy \
    -u HTTPS_PROXY -u https_proxy -u NO_PROXY -u no_proxy \
    .venv/bin/python run_tests.py --mode all
  ```

  任何直接调 `.venv/bin/python` 的命令(包括冒烟脚本)都要带这串清理,否则必崩;
  用 `run_tests.sh` / `run_smoke.sh` 可免于此。

- 另注:`run_tests.py` 通过 subprocess 调 pytest。把输出接进管道(如 `| tail`)看到的是管道退出码,
  会掩盖真实失败,必须单独确认 `$?` 或直接用 `run_tests.sh`。

## 工作留痕

任务过程文件写入项目本地 `.Codex/` 目录(已 git ignore,不入库):

```
.Codex/
├── context-summary-<任务名>.md   ← 编码前上下文摘要
├── operations-log.md             ← 决策与操作记录
└── verification-report.md        ← 验证结果
```
