# Nai Core Agent 设计稿 v2——pi 设计哲学 × LangChain/LangGraph 底座

> **2026-10-04 用户终裁修订版**：底座回归 LangChain/LangGraph，pi 仅作设计哲学参考，域语义层不变。
> 替代 2026-10-03 v1（自研裸写版——已实施 P1-P4 并合入 main，但底座选型偏离用户意图，本稿为修正方向）。

## 一、三层架构（用户终裁）

```
┌─────────────────────────────────────────────────────┐
│  策略层（Nai 域语义——自研，不变）                      │
│  提案三通道 / 审核三档 / create 闸门 / scope 冻结     │
│  预算三口径 / 压缩策略 / 墓碑 / 章号锚定              │
├─────────────────────────────────────────────────────┤
│  设计层（pi 思想——参考蓝图，非代码）                  │
│  stopReason 分类学 / 极简工具面 / 取消即消息          │
│  压缩六节模板 / 双层循环语义 / 节点幂等薄函数          │
├─────────────────────────────────────────────────────┤
│  底座层（LangChain + LangGraph——框架扛）             │
│  LangChain: model 抽象 / provider 矩阵 / 消息格式    │
│  LangGraph: StateGraph 循环编排 / 条件边 / checkpointer│
└─────────────────────────────────────────────────────┘
```

**核心原则**：pi 教我们「怎么想」（分类学/极简/取消语义），LangChain/LangGraph 替我们扛「通用机器」（SDK 形状/重试/provider 切换/checkpoint），我们只写「域策略」（提案/预算/压缩策略）。

## 二、与 v1（自研裸写版）的关系

| 层 | v1 实现（已合 main） | v2 方向 | 迁移判断 |
|---|---|---|---|
| stopReason 分类学 | ✅ core/loop.py 硬分支 | **保留**——设计不变，改由 LangGraph 条件边表达 | 策略层原样迁移 |
| 取消即消息 | ✅ core/provider.py CancelledError 收束 | **保留**——LangGraph interrupt 原生支持 | 接口适配 |
| 压缩链 | ✅ core/compaction.py 六节摘要 | **保留**——策略不变，挂点改在 LangGraph 节点 | 策略层原样迁移 |
| 预算三口径 | ✅ core/budget.py | **保留**——策略不变 | 同上 |
| 循环执行器 | ⚠️ core/loop.py 裸写循环 | **替换**——LangGraph StateGraph 做循环 | 底座换框架 |
| provider 层 | ⚠️ core/provider.py openai SDK 裸写 | **替换**——LangChain model 抽象 | 底座换框架 |
| 工具执行器 | ✅ core/tools.py 三通道 | **保留**——策略不变 | 策略层原样迁移 |
| 事件守护 | ✅ core/events.py | **保留**——前端零改动验收线 | 策略层原样迁移 |

**一句话**：v1 的策略层全部保留（它是正确的），v1 的执行层（loop+provider）换成 LangChain/LangGraph。改动面集中在两个文件的底座重构。

## 三、迁移路径（从当前 main 出发）

### 阶段 A：底座替换（改动最大的阶段）

**A1. provider 层换 LangChain**
- `core/provider.py` 的 openai SDK 裸写改为 `langchain_openai.ChatOpenAI`
- 保留：max_retries=0 纪律、reasoning_content 处置、usage 采集、compat 开关
- 收益：provider 矩阵（15+ 供应商）、标准化消息格式、SDK 形状问题社区解
- 改动量：~200 行重写（接口面不变，对外仍暴露 ProviderEvent 流）

**A2. 循环执行器换 LangGraph StateGraph**
- `core/loop.py` 裸写循环改为 `langgraph.graph.StateGraph`
- 节点映射：
  - `prepare` → prepare_next_turn 节点（压缩挂入点）
  - `respond` → model 调用节点（LangChain  invoke/stream）
  - `execute` → 工具执行节点（挂 beforeToolCall/afterToolCall 钩子）
  - 条件边：无 toolCall→end；有→execute→respond 循环；stopReason 硬分支
- 保留：轮次软闸（max_rounds=8）、length 终态拒、terminate 拉闸、steering 注入
- 收益：checkpoint 语义、interrupt 原生、time travel
- 改动量：~400 行重写（对外仍暴露 Nai 事件流）

**A3. 挂点适配**
- 域策略挂点（beforeToolCall/afterToolCall/prepare 预算检查）改为 LangGraph 节点内调用
- 事件序适配层保留（pi 事件→Nai tool/chunk/final 翻译层——前端零改动验收线不变）

### 阶段 B：验证（与 v1 验收线相同）

- 前端事件序不变（硬线）
- 压缩 30 轮演示（与 v1 同标准）
- 取消传播链实测
- 预算三口径验证
- 工具路由评测 ≥85%

### 阶段 C：清理

- 删除 v1 的裸写 loop/provider（策略层模块保留）
- 测试迁移（策略层测试原样；底座测试改为 LangGraph 适配）

## 四、pi 设计哲学要点（从 v1 保留，不因底座变化而变）

1. **stopReason 七态分类学**（pending/stop/length/toolUse/error/aborted/deferred）
2. **length → 拒执行整批 toolCall**（截断的 toolCall 参数可能不完整，一律不执行）
3. **error/aborted → 保已登记提案直接收尾**（不重试不吞）
4. **取消不是异常，是一条结构化消息**
5. **压缩六节模板**（保章号/设定账本键/剧情指针）
6. **切点不破工具对**（工具结果必须跟着其调用）
7. **截断/错误摘要拒落盘**（残缺文本不得成为检查点）
8. **极简工具面**（只给模型需要的，不给多余的）
9. **双层循环**（内层工具轮+外层 follow-up 队列轮询）
10. **节点幂等薄函数**（输入输出显式、无隐藏内部状态）

## 五、域语义层（完全不变，从 v1 原样保留）

- 提案三通道+同事务采纳链
- 审核三档+create 全档闸门
- scope 冻结+ContextScopeError 穿透
- 预算三口径（次数+token+钱）+降级分级
- 墓碑+章号锚定+墓碑去污染
- RAG 投影+四层记忆
- ContextPack+memory_head_version 栅栏

## 六、v1 遗留问题清单（v2 一并处理）

| # | 问题 | 处置 |
|---|---|---|
| 1 | 压缩挂点零接线（compaction 无外部调用者） | A2 的 prepare 节点接入 |
| 2 | deepseek-flash 未注册 ModelInfo | A1 的 LangChain 注册表统一 |
| 3 | SDK 工具增量形状（已修 #38） | LangChain 标准化消解 |
| 4 | async 接缝（已修 P4） | LangGraph 原生 async 消解 |
| 5 | reasoning_content 处置 | LangChain 消解 |

## 七、量级与排期

| 阶段 | 内容 | 量级 |
|---|---|---|
| A1 | provider→LangChain | ~200 行重写+测试 |
| A2 | loop→LangGraph StateGraph | ~400 行重写+测试 |
| A3 | 挂点适配+事件序适配层 | ~100 行 |
| B | 验证（同 v1 验收线） | 评测+走查 |
| C | 清理 v1 裸写件+测试迁移 | ~100 行删除 |

合计改动面 ~700 行重写+100 行适配，策略层零改动。

## 八、与外部评审的对照

| 评审建议 | v1 处置 | v2 处置 |
|---|---|---|
| 使用 LangGraph checkpointer | 驳回（自建） | **部分采纳**——checkpoint 作为可选能力，域状态仍在 SQLite |
| LangChain 标准化消息 | 驳回（自有契约） | **采纳**——LangChain 标准化做底座，域策略经适配层对接 |
| provider 矩阵 | 单协议裁剪 | **保留裁剪**——但底座是 LangChain，切供应商=改配置 |
| 可观测 | 自研埋点 | 不变（域指标仍自研，底层调用 LangChain 回调可补） |
