# 墨枢架构文档集

> 权威版（canonical）· 由 team-lead 维护 · 2026-10-03 整理建集
> `.Codex/` 同名文件为工作稿/过程稿，冲突时以本目录为准。

## 阅读顺序

| # | 文档 | 内容 | 状态 |
|---|---|---|---|
| 1 | [system-architecture.md](system-architecture.md) | 实态架构图（双轨期）+ 评审记录（两轮）+ 目标边界映射 | **入口文档** |
| 2 | [core-agent-design.md](core-agent-design.md) | Nai Core Agent 设计稿 v2（pi 哲学 × LangChain/LangGraph 底座） | **v2 终稿·候实施** |
| 3 | [form-factor-decision.md](form-factor-decision.md) | 形态三轴决策（壳 B/底座 pi 参考/真源导出） | 终稿·已拍板 |
| 4 | [shell-desktop-plan.md](shell-desktop-plan.md) | 桌面壳四期方案 | 终稿·P1 实施中 |
| 5 | [architecture-backlog.md](architecture-backlog.md) | 架构债务七条（高优三/中优二/半覆盖二） | 活文档 |

## 研究材料（不编入，路径备查）

- pi-mono 源码研究：`.Codex/pi-mono-source-map.md`（六块架构地图）
- pi-mono 本地克隆：`/Users/hades/Documents/Projects/pi-mono-study`

## 决策快照（2026-10-04 终裁修订）

- **底座终裁（2026-10-04 用户令）**：LangChain+LangGraph 作底座（框架扛通用机器），pi 仅作设计哲学参考（极简/分类学/取消语义），域语义层不变——**替代 10-03 的「自研裸写」方向**
- v1（自研裸写）已合 main 并工作（42 PR），但偏离用户意图——v2 修正方向为「底座换回框架、策略层保留」
- 评分轨迹：8 → 6.5（两轮外部评审）→ 目标 8.5+（v2 底座回归+P0 三项）
- 选型会六定案（2026-10-03）：①可观测=自研埋点 ②durable=自建+清单验收 ③VectorStore=Qdrant embedded ④BM25=FTS5 trigram+RRF ⑤token=chars/3 ⑥降级=明示请作者+不静默

## 维护纪律

- 架构级 PR 须同步本目录；
- 评审/决策记录只增不删，翻案须新证据；
- 选型变更经 pm 选型会 → 本 README 决策快照更新。
