# 墨枢形态决策分析(桌面/Web/混合)——决策文档 v2.1

- 作者:pm;状态:**v2.1**(三注全落文件版:backend sidecar-and-filesource-feasibility.md、frontend shell-frontend-feasibility.md;pi 增补为 lead 战略令),供用户拍板
- **底座轴终裁(2026-10-03,覆盖 §六A 与 §七拍板点② 原推荐):不换架构,参考 pi Core 从头搭建核心 agent**——B+ 中间件形状(pi TS sidecar)作废(pi-spike-acceptance.md 已标废);前置:pi-mono 源码研究(.Codex/pi-mono-source-map.md),承接稿:Nai Core Agent 设计稿(.Codex/core-agent-design.md)候看板。壳轴(B 只出稿不动工)与真源轴(DB+单向导出)推荐不变。
- 纪律:只读分析+本文档(lead 派令授权);来源:【DeepWrite README 实读】【pi 公开资料 2026-10-03 检索】【pm 架构底账】【代码实测】【backend/frontend 技术注记文件版】
- 关联:.Codex/ledger-pm-architecture-map.md、.Codex/sidecar-and-filesource-feasibility.md、.Codex/shell-frontend-feasibility.md

## 一、决策问题

Nai 以什么形态交付:纯 Web(现状)、Web 核心+桌面壳、还是桌面原生重写?外加两条增广轴:**Agent 底座**(自研 runtime vs pi)与**真源**(DB vs 文件)。本文将其整理为**三个可独立拍板的轴**,避免把「外壳、底座、数据架构」捆在一个三选一里强行耦合。

## 二、竞品事实:DeepWrite 深读【README 实读】

- 定位:「面向创作者的本地优先 AI 写作智能体工作台」。Electron 桌面应用,GitHub Releases 分发,5.1k star,更新活跃。
- 架构:Electron 多进程,模型走 **pi runtime 适配层**(Node/TS,**无 Python 服务端**);数据**文件真源**(json+Markdown,明言可用 Git/同步盘管理);写入 **diff 先行**(所有写入先展示差异、接受才保存、防静默覆盖)——与 Nai 候选制+版本防护同构,两案独立演化出同构安全观,佐证该设计是域内正解。
- 功能面:素材库/技能库/子智能体/拆书/三栏工作台。
- **对照结论:DeepWrite 已占位「桌面原生+文件真源+pi 底座」整条路线。** Nai 的差异化不在重走这条路,而在服务端重基建(见三)。

## 三、Nai 现状资产盘点(形态视角)

全部重资产在**服务端**(Python/FastAPI):持久任务(租约 CAS+断连恢复+run_recovery)/双生成链(LangGraph 对话流+流水线+DAG)/三层预算/RAG 投影/提案三通道+**同事务采纳链**(版本快照+审计+哈希防覆盖)/审核三档+create 闸门/ContextPack+memory_head_version 栅栏/四层记忆。

**关键判断一:以上资产 100% 形态无关**(HTTP 服务能力,浏览器或壳访问不改变任何一行)——壳轴(B 档)可行性之根。
**关键判断二:其中「数据守护」子集(采纳链/审核/栅栏/预算执行)是域策略,不是 agent 循环**——底座轴(pi)可替换的只是循环壳,域策略原地不动(见六 A)。

## 四、壳轴三档评估

| 维度 | A 纯 Web 现状 | B Web 核心+桌面壳 | C 桌面原生重写 |
|---|---|---|---|
| 目标用户 | 愿跑 npm/uv 的技术型作者 | 普通网文作者(下载即用) | 同 B |
| 分发 | repo+README 自部署 | 安装包(对标 DeepWrite) | 同 B |
| 工程量 | 0 | **backend 8-13+frontend 8-12=单机全案 16-25 人日**【两注记文件版】 | 几人月级 |
| 服务端资产 | 保留 | **保留 100%** | 归零重做(LangGraph→Node) |
| 主要风险 | 分发门槛锁死受众 | 进程/端口生命周期;key 分发(产品配置面) | DeepWrite 已占位,零增量 |

- A 的实质:「没有外壳的桌面应用」——用户已在用桌面式体验,缺的只是**到达**。A 的问题不在体验在分发。
- C 排除:①服务端重基建是差异化本体;②C 路线竞品已占位,追赶无增量;③「sidecar 不可打包」的回桌条件已被 backend 注记否决(embedded Python 风险集中可控)。
- **B 一句话:保住差异化(服务端)+得到分发(安装包)。**

## 五、真源轴:文件化变体评估

- 文件真源代价【backend 注记八条清单】:乐观锁/提案**同事务采纳链(最大重构点 1-2 人周)**/哈希防覆盖/栅栏/章号权威(重演刚修好的 N2 锚定)/RAG watcher/迁移/603 测试夹具——合计 **4-6 人周**,且**事务语义降级是架构级损失**。
- **定案(backend 反问作答支撑):DB 真源+单向自动导出 Markdown——1-2 人日,吃作者侧收益 70-85%**(可 grep/备份/任意编辑器/Git 版本史/防锁死)。吃不到的恰是最贵的双向回写。渐进:单向→半双向(检测外部修改提示导入)→真双向,按需求信号逐级不预支。
- 文件真源为远期选项,触发条件=「多工具协作编辑」强需求实锤。**.md 文件关联/导入管线同理候 §五定案节奏,止步对话框+预览层不提前**(frontend 注记④)。

## 六、工程量注记

### 6.1 backend:sidecar+文件化【详 .Codex/sidecar-and-filesource-feasibility.md】

embedded Python 主路径(python-build-standalone 解释器+venv 随包,壳 spawn uvicorn;**不选 PyInstaller**——LangChain/LangGraph entry_points 动态加载是冻结深坑,embedded 整体化且「测试过的 venv=发行的 venv」):打包布局 2-3 人日(体积 ~500MB-1GB 可裁)/数据目录迁移 1-2/**key 桌面分发 1-3(产品配置面:key 不内置,最小=首启引导写 env)**/启动管理(动态端口+健康检查+崩溃重启+孤儿清理)2-3/CI 签名公证 3-5。**合计草稿 5-8、可分发 8-13 人日**。坑 top3:动态导入(embedded 化解)/进程端口生命周期/key 分发形态。

### 6.2 frontend:桌面壳【文件版 .Codex/shell-frontend-feasibility.md,树 abf8c3d 逐项亲核】

**事实底座(亲核)**:全页面 'use client' 零 SSR 面(app/ 全树);API 基址构建期绝对地址从不假设同源(mutator.ts:10);Bearer token 客户端存储;SSE=自实现 fetch 流 getReader 非 EventSource(sse.ts:67);零在线字体/零 next/image;Next 15.1.4+React 19+MUI 6.3。

- **选型:Tauri v2 主路径**,Electron 应地貌测——前端零 Node 运行时依赖,轻量(包体 MB 级 vs 100MB+)完整兑现;MUI6.3+React19 壳内无 SSR,兼容顾虑不适用,风险收敛为双平台 WebView **像素走查矩阵**;Rust 工具链归构建运维。
- **静态导出可行**(零 SSR 面),唯一硬坑:`/novels/[id]` 动态段×2 不可枚举→迁 workspace 既有 query 模式(?novel=),两页已 'use client',**1-1.5 人日**;双 sidecar(壳内 next start)为劣化应急(+2-3 仅撞墙启用)。
- **SSE 特有坑三件**:①tauri:// origin 跨域→壳用 **http 资产服务形态**(http://localhost:<port>)+后端 CORS 一行放行,避免 Tauri HTTP 插件绕 CORS 引入流式转发复杂度;②**构建期 env vs 后端动态端口错配(暗雷)**→运行时基址覆盖(window.__NAI_API_BASE__ 或 mutator 覆盖点)0.5-1 人日;③macOS WKWebView App Nap 后台节流→Tauri 禁用开关,走查项。
- **分项量表**:静态导出 1-1.5/壳初始化(窗口/菜单/深链/资产)1-2/基址覆盖+CORS 衔接 0.5-1/.md 关联+导入管线 1.5-2(**与文件真源安全机制强耦合,候 §五定案,止步对话框+预览层**)/主题与离线字体 0-0.5/更新通道(tauri-plugin-updater+minisign,Win 签名证书年费流程成本与 backend 合并排)1-2/CI+双平台走查 2-3/应急双 sidecar +2-3。
- **总人日:单机形态 8-12;混合形态(壳只包前端连云端)5-8**;与 backend 8-13 同构可相加,**单机全案 16-25 人日**。坑 top5:动态路由 query 化/运行时基址/origin CORS/.md 耦合顺序/Win 签名流程。

## 六 A、Agent 底座轴:pi 评估(lead 增补,一等选项)

**pi 画像【公开资料检索】**:Mario Zechner(badlogic,libGDX 作者)的 TypeScript 极简 agent 底座(pi-mono/@mariozechner/pi-coding-agent);agent-tool-session 小循环+自有 extension 系统(刻意不做 MCP 默认);成熟面=通用机器:循环健壮/多 provider/会话恢复/上下文压缩/扩展。DeepWrite 即以 pi-runtime-adapter 作底座。

**分层论证(底座 vs 域语义)**:pi 的成熟在**通用机器层**,Nai 的资产在**域策略层**(提案/审核三档/scope 冻结/章号锚定/预算)。两层正交——域策略**可全数做成 pi 之上的工具与策略层**,不必动 FastAPI 的守护逻辑。今日实证注记(lead ③):吞异常/Cancel 分叉类**底座雷在 pi 上大概率免费消失**(本轮流式 P0 诊断踩的正是这类雷)。

**B+ 形态:Fermi 分层**——Tauri 壳 + **pi agent 服务(TS sidecar,只管对话循环+流式+会话恢复)** + FastAPI 域服务(全部工具执行+真源+守护):
- **工具协议**:pi 的 tools 注册为**薄代理**→HTTP 调 FastAPI 现成工具执行面(execute_read_tool/execute_capability_tool 即现成端点化基础)——提案工具/检索工具逐个映射,pi 侧零业务逻辑;
- **安全域不动**:scope 冻结(manifest)/采纳链/预算执行仍在 FastAPI 工具端内核,信任边界不扩到 TS 侧;
- **SSE 转接**:pi 会话流→壳直连或经 FastAPI 转发,需一层转接设计(评估点);
- **迁移分期**:新链路双轨(pi 跑新对话轮,LangGraph 链保留回退)→灰度切换→下线自研循环;LangChain/LangGraph 依赖若随之下线,sidecar 体积与冻结坑同步缩减(与 6.1 正反馈)。
- 工程量:B+ 未定价(需一轮 backend 合议 pi 工具协议+SSE 转接+双轨期),定性**大于 B 壳、远小于 C**,且与壳轴正交可分序。

## 七、推荐与分期路线

**两轴解耦,三个拍板点**:

**拍板点①壳轴:推荐 B(Tauri v2+embedded Python sidecar),现在做**。总 16-25 人日分四期:P1 壳 MVP spike(一周小步:静态导出+动态路由 query 化+壳 spawn+动态端口+**运行时基址覆盖**+健康检查,验证失败才回桌重评)→P2 数据目录迁移+首启引导(含 key 写入)→P3 更新通道+CI 签名公证(Win 证书与 backend 合并排)→P4 .md 关联+导入管线(候 §五节奏)。**分发形态子决策:单机优先**(与本地 LLM 心智一致;云端混合为远期增量,壳侧届时 5-8 人日区间,不浪费);backend sidecar 数据面/更新面随版本走的方案由 backend 补报。
**拍板点②底座轴:推荐 B+(pi),作为独立二期工程,不与壳耦合**。理由:分发痛点急(A 档到达问题每个新作者都撞,壳先落地即止血),底座重构是质量投资(底座雷消除+会话恢复/压缩免费得);两轴正交,分序执行总风险小于并行。启动前置:backend 一轮 pi 工具协议+SSE 转接+双轨分期合议。
**拍板点③真源轴:推荐维持 DB+单向导出(1-2 人日,随批2 拼车,格式与稿纸卡同源 Markdown)**;文件真源与双向回写按五节渐进路线以需求信号触发。

## 八、决策后验证步骤

1. **装 DeepWrite 试用**:体验层对标(启动/三栏手感/diff 流程/包体积),作 B 壳 spike 基线(建议 ux 会话或用户执行;未公证包属系统侵入,pm 不代装)。
2. 选 B 即启动 **P1 spike**(验证清单:静态导出+动态路由 query 化/壳 spawn+动态端口/**运行时基址覆盖**/http 资产形态 origin+CORS/健康检查;一周小步)。
3. 选 B+ 先 **backend pi 合议会**(工具协议/SSE/双轨),产出 B+ 工程量定价后再排期。
4. 单向导出随批2:保存钩子挂采纳链后自动落盘 per-chapter md+manifest。
