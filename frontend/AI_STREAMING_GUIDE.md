# AI 请求、持久任务与候选

工作区的创作对话、高级续写、局部改写统一经持久生成任务执行。HTTP 入队与实际模型运行分开；页面退出只中断本页等待，作者点击停止才向服务器发送取消命令。

## 当前链路

| 入口 | 请求与恢复 | 正文采纳 |
|---|---|---|
| 常驻对话 | `POST /generation/jobs`，kind 为 chat；历史合并 WritingTurn 与尚未建立轮次的真实任务 | 讨论、规划和检查只供参考；正文类任务返回 proposal，作者确认后保存 |
| 高级续写 | kind 为 continue，保留文风、节奏、目标长度；按作品和章节恢复最近任务 | 服务器验证原文版本、哈希和生命周期后追加正文 |
| 局部改写 | kind 为 rewrite；选区下标从 UTF-16 转为 Unicode 码点 | 原选区和可编辑候选对照，`candidate_content` 随确认命令提交 |
| 审核与其他已有流接口 | 原 SSE 协议继续可用 | 按业务结构展示，不当作创作任务已经完成 |

公共客户端为 `lib/generationJobs.ts`，高级续写和改写共用 `hooks/useGenerationTask.ts`。任务的状态为 queued、running、completed、failed、cancelled；HTTP 200/202 不代表模型完成。失败或取消时不得展示为可采纳成功结果。

## 恢复和停止

- 入队请求包含 UUID、作品生命周期和原工具 payload；chat 内外 request_id 一致。服务端冻结章号、版本、生命周期等来源。
- 对话按小说恢复历史、每 2 秒轮询未完成记录。已入队而尚无 WritingTurn 的任务保留真实 job_id、问题、模式、来源标题，显示等待执行；不伪造数据库轮次 ID。
- 高级续写与改写按作品、章节、能力查询最近 30 项任务，再按章节生命周期核验；可选择本章旧任务查看之前的候选。失败的新任务不会使旧候选永久不可见。
- 切作品、章节生命周期变化或卸载时 AbortController 中止读取，并忽略迟到结果。取消入口调用 `/generation/jobs/{id}/stop`；未知是否送达时保留错误，提示刷新核对。
- 服务重启后不自动重放收费模型请求；过期任务记录明确失败，作者重新生成时使用新 request_id。保留对话草稿与候选，不把断网当成功。

## 候选保存与身份

`WritingProposalActions`、`useWritingProposal` 和 `writingProposalApi` 共用服务端采纳命令。显示候选时先读取真实状态，刷新后已采纳和已拒绝状态仍可恢复。

正文类生成前要求作者身份核验完成且正文已保存。采纳前核验当前小说、章节生命周期、原文版本和 SHA-256；服务器在同事务中写新正文版本与采纳审计。相同确认重试复用 request_id，编辑候选内容后生成新的命令身份。

确认期间再编辑正文时，保留本机新稿并提示服务器已经保存，不用回包覆盖。重新保存可进入现有版本冲突流程。生成新章使用对话的「起草下一章」，作者点击「确认创建新章」后才创建章节。

## 本轮参考来源

`ContextSources` 只展示服务端响应中的 context_manifest。来源包含 L1 简介、结构化大纲、核心状态和原文短摘；可按不可变 revision 回查。没有清单的旧记录不补造今天的来源，省略与失效警告如实显示。

清单是共享上下文的来源记录，不等于完整 Prompt、全书阅读证明或候选采纳条件。模型只接收预算允许的历史与正文；界面加载的全部历史不会自动全部传给模型。

## SSE 客户端契约

保留的流式接口统一使用 `lib/sse.ts`。`chunk`/`content` 传正文片段，`metadata`/`data` 传来源或工作流信息，`done` 是显式完成标记，`error` 必须转为失败。EOF 缺少 done 时抛出 SSEUnexpectedEOFError；AbortSignal 取消 reader。

工作区主对话和高级工具不宣称逐 token 输出。实际模型、usage、耗时以服务端执行记录为准；缺失值保持未知，不能用动画或估算替代。

## 验证

前端测试覆盖持久任务 HTTP 字段、排队历史恢复、显式停止与退出分离、来源生命周期、Unicode 重复原句选区、幂等确认、在途新稿、冲突候选保留、取消终态和历史原文恢复。

运行 `npm run lint && npm run typecheck && npm run test && npm run build`。Node 25/26 环境使用 `NODE_OPTIONS=--no-experimental-webstorage`，避免原生 webstorage 与 jsdom 冲突。自动化替身与隔离 UI fixture 都不代表真实模型效果评测。
