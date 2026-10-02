# AI 小说创作系统 — 前后端 API 对接文档

- 后端框架：FastAPI；基址：`http://127.0.0.1:8000`；交互式文档：`http://127.0.0.1:8000/docs`
- 前端 SDK 参考：`frontend/lib/api.ts`、`frontend/lib/sse.ts`
- 本文依据 `backend/app/main.py`、`backend/app/api/routes/`、`backend/app/models/` 与 `frontend/lib/` 现行代码撰写，未编造端点或字段；标注「待核对」处为路由层未暴露完整结构。
## 一、总览
### 路由挂载前缀（main.py）

| 模块 | 前缀 |
|------|------|
| 健康检查 | `/api`（`/api/health`、`/api/ping`） |
| 用户认证 | `/api/auth` |
| 小说管理 | `/api/novels`（章节嵌套其下） |
| 角色管理 | `/api/characters` |
| Story Bible | `/api/story-bible`（facts/events） |
| 统一 MCP | `/api/mcp`（capabilities/execute/audit） |
| 创作对话 | `/api/writing-chat`（持久历史、完整回复与停止） |
| 章节记忆 | `/api/novels/{id}/chapters/{chapter_id}/digest`、`revisions` 与 `/api/memory-jobs` |
| 内容生成 | `/api/generation`（含 SSE） |
| 文风样本 | `/api/style` |
| 资料检索 | `/api/research` |
| RAG 调试 | `/api/rag` |
| 一致性检查 | `/api/consistency`（SSE） |
| 章节审核 | `/api/review`（含 SSE） |
### 认证方式

- 除健康检查、注册、登录、`/api/mcp/capabilities` 外，全部端点要求 **Bearer JWT**：`Authorization: Bearer <access_token>`。
- Token 取 `POST /api/auth/register` 或 `/login` 返回的 `access_token`；前端存 `localStorage` 键 `token`。
- 无 token/无效 token：`401`，`detail` 为「无效的认证令牌」或「用户不存在」。
### 通用错误格式
错误响应体为标准 `{"detail": ...}`；校验失败时 `detail` 为数组 `[{"loc":[...],"msg":"...","type":"..."}]`。前端解析见 `api.ts` 的 `extractApiErrorMessage()`（优先 `detail`，其次 `message`）。
### 状态码语义

| 码 | 语义 |
|----|------|
| 200/201/204 | 成功 / 创建成功 / 删除成功（无体） |
| 400 | 参数错误、名称重复、用户被禁用 |
| 401 | 未认证或 token 无效 |
| 403 | 无权访问他人资源 |
| 404 | 资源不存在（或无权时统一返回 404） |
| 409 | 章节号冲突、章节版本冲突（乐观锁） |
| 422 | 请求体校验失败 |
| 500 | 服务端异常 |
| 501 | 功能未实现（MCP 明确返回） |
### 409 章节版本冲突语义（乐观锁）

- 更新章节（`PUT .../chapters/{chapter_id}`）**必须**携带 `expected_version`（客户端上次读到的 `version`）。
- 服务端以 `WHERE id=? AND version=expected_version` 更新，命中 0 行返回 `409`：`{"detail":"章节已被其他保存更新，当前版本为3，请刷新后重试"}`，数字为服务端当前版本号。
- 章节号冲突同样 `409`：`detail` 为「章节 X 已存在」「目标章节号已存在」或「分配下一章节号时发生并发冲突，请重试」。
### 字数统计规则

`Chapter.word_count`、`ChapterSummary.word_count` 与小说统计 `total_words` 均按**非空白 Unicode 字符数**计算：忽略组合标记（如拼音声调、重音）和零宽连接符；空白与换行不计入。后端实现在 `app/core/text_stats.py`，前端实现在 `frontend/lib/textStats.ts`，两端语义一致。
### 健康检查

| 端点 | 认证 | 响应 |
|------|------|------|
| `GET /api/health` | 否 | `{"status":"healthy","app_name":...,"version":...}` |
| `GET /api/ping` | 否 | `{"message":"pong"}` |
## 二、认证（/api/auth）
### POST /api/auth/register — 注册（201 → Token）

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| username | string | 是 | 3–50 |
| email | string | 是 | 合法邮箱 |
| password | string | 是 | 6–50 |

响应：`Token` → `access_token`、`token_type`（`"bearer"`）、`user`。错误：`400` 用户名已存在 / 邮箱已被注册。
### POST /api/auth/login — 登录（200 → Token）

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| username | string | 是 | 3–50 |
| password | string | 是 | 6–50 |

响应：`Token`。错误：`401` 用户名或密码错误；`400` 用户已被禁用。
### GET /api/auth/me — 当前用户（200 → UserResponse）
响应：`id`、`username`、`email`、`is_active`、`created_at`。错误：`401`、`400` 用户已被禁用。
## 三、小说（/api/novels）
### POST /api/novels/ — 创建（201 → NovelResponse）

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| title | string | 是 | 1–200 |
| genre | string | 否 | ≤50 |
| description | string | 否 | ≤8000 |
| worldview | string | 否 | ≤50000 |

响应：`id`、`title`、`genre`、`description`、`worldview`、`user_id`、`created_at`、`updated_at`。
### GET /api/novels/ — 我的小说列表（200 → List[NovelResponse]）
查询：`skip`（默认 0）、`limit`（默认 100）。
### GET /api/novels/statistics — 聚合统计（200）
响应：`{"items":[{novel_id, chapter_count, total_words}]}`。
### GET /api/novels/{novel_id} — 详情（200 → NovelResponse）
错误：`404` 小说不存在；`403` 无权访问此小说。
### GET /api/novels/{novel_id}/export.txt — 整本 TXT 导出（200）
需要认证。返回 `text/plain; charset=utf-8`，正文带 UTF-8 BOM，包含书名、简介及按章号排序的全部已保存章节（不受章节列表分页上限影响）。`Content-Disposition` 提供附件文件名与 UTF-8 中文文件名，`Cache-Control: no-store`。小说不存在或不属于当前作者均返回 `404`。

前端以 Blob 下载文件。仅导出服务端已保存正文，不包含未保存的本地草稿、世界观或事实账本。当前一次读取全书，超大体量作品仍需后续流式导出优化。
### PUT /api/novels/{novel_id} — 更新（200 → NovelResponse）
字段（全可选，至少一项否则 422）：`title`(1–200)、`genre`(≤50)、`description`(≤8000)、`worldview`(≤50000)，均可传 null 清空。错误：`404`、`403` 无权修改此小说、`422` 空更新。
### DELETE /api/novels/{novel_id} — 删除（204）
经 ORM 级联删除章节、对话、事实、事件、角色关系与出场等附属数据，RAG 派生索引后台清理。错误：`404`、`403`、`500`。
## 四、章节（/api/novels/{novel_id}）
### POST /api/novels/{novel_id}/chapters — 创建（客户端指定章号，201 → ChapterResponse）

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| chapter_number | int | 是 | >0 |
| title | string | 是 | 1–200 |
| content | string | 否 | ≤500000，默认空 |

错误：`404`、`403` 无权为此小说添加章节、`409` 章节 X 已存在。
### POST /api/novels/{novel_id}/chapters/next — 创建下一章（服务端分配章号，201 → ChapterResponse）

**服务端原子分配「最大章号 + 1」**，客户端不传章号；并发由数据库唯一约束兜底。

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| title | string | 否 | 1–200 |
| content | string | 否 | ≤500000，默认空 |

错误：`404`、`403`、`409` 分配下一章节号时发生并发冲突，请重试。
### GET /api/novels/{novel_id}/chapters — 章节列表（分页，摘要不含正文，200）
查询：`page`（≥1，默认 1）、`page_size`（1–100，默认 50）。

响应 `ChapterPageResponse`：`items`（`ChapterSummary[]`，不含 `content`）、`total`、`page`、`page_size`、`has_more`。`ChapterSummary`：`id`、`novel_id`、`chapter_number`、`title`、`word_count`、`version`、`created_at`、`updated_at`。错误：`404`、`403`。
### GET /api/novels/{novel_id}/chapters/{chapter_id} — 章节详情（含正文，200 → ChapterResponse）
响应：`id`、`novel_id`、`chapter_number`、`title`、`content`、`word_count`、`version`、`created_at`、`updated_at`。错误：`404` 章节不存在、`403`。
### PUT /api/novels/{novel_id}/chapters/{chapter_id} — 更新（乐观锁，200 → ChapterResponse）

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| expected_version | int | **是** | ≥1（客户端读到的版本） |
| chapter_number | int | 否 | >0 |
| title | string | 否 | 1–200 |
| content | string | 否 | ≤500000 |

除 `expected_version` 外至少提供一个业务字段，否则 `422`。响应 `version` 自增 +1。错误：`404`、`403`、`409` 版本冲突（见总览）、`409` 目标章节号已存在。
### DELETE /api/novels/{novel_id}/chapters/{chapter_id} — 删除（204）
错误：`404`、`403`、`500`。
## 五、角色（/api/characters）
### POST /api/characters/ — 创建（201 → CharacterResponse）

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| novel_id | int | 是 | >0 |
| name | string | 是 | 1–100 |
| age | int | 否 | 0–1000 |
| gender | string | 否 | ≤20 |
| occupation | string | 否 | ≤100 |
| appearance | string | 否 | ≤4000 |
| personality | string | 否 | ≤4000 |
| background | string | 否 | ≤8000 |
| skills | string[] | 否 | ≤50 项，每项 1–200 |
| relationships | object | 否 | ≤50 键，序列化 ≤20000 |
| character_arc | string | 否 | ≤8000 |
| importance_level | string | 否 | `main`/`secondary`/`minor`，默认 `secondary` |
| first_appearance_chapter | int | 否 | >0 |

响应含 `id`、`novel_id`、上述字段、`ai_analysis`、`created_at`、`updated_at` 等。错误：`404` 小说不存在或无权访问；`400` 角色名称已存在。
### GET /api/characters/{character_id} — 详情（200 → CharacterResponse）
错误：`404` 角色不存在 / 无权访问该角色。
### GET /api/characters/novel/{novel_id} — 列表（200 → List[CharacterResponse]）
查询：`skip`（≥0，默认 0）、`limit`（1–100，默认 100）、`importance_level`（≤20，可选）。
### PUT /api/characters/{character_id} — 更新（200 → CharacterResponse）
字段全可选（含 `last_appearance_chapter`，其余约束同创建）。错误：`404`、`400` 角色名称已存在。
### DELETE /api/characters/{character_id} — 删除（204）
错误：`404`、`500`。
### POST /api/characters/relationships — 创建角色关系（201）

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| novel_id | int | 是 | >0 |
| character_a_id | int | 是 | >0 |
| character_b_id | int | 是 | >0 |
| relationship_type | string | 是 | ≤50 |
| description | string | 否 | ≤4000 |
| strength | int | 否 | 1–10，默认 5 |
| development_stage | string | 否 | ≤50 |
| established_in_chapter | int | 否 | >0 |

响应额外回传 `character_a_name`、`character_b_name`。错误：`404` 小说/角色不存在或无权访问；`400` 角色不属于指定小说。
### GET /api/characters/{character_id}/relationships — 关系列表（200）
响应：`List[CharacterRelationshipResponse]`。
### GET /api/characters/novel/{novel_id}/network — 关系网络（200）
响应：`{novel_id, characters, relationships, network_analysis}`。
### POST /api/characters/appearances — 创建出场记录（201）

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| character_id | int | 是 | >0 |
| chapter_id | int | 是 | >0 |
| appearance_type | string | 否 | `main`/`supporting`/`mentioned`，默认 `supporting` |
| description | string | 否 | ≤4000 |
| importance_in_chapter | int | 否 | 1–10，默认 5 |
| status_changes | object | 否 | ≤50 键，序列化 ≤20000 |

响应含 `character_name`、`chapter_number`。错误：`404` 角色/章节不存在或无权访问、章节不属于同一小说。
### GET /api/characters/{character_id}/timeline — 时间线（200）
响应：`{character_id, character_name, appearances, ...}`。
### POST /api/characters/mcp/execute — 角色 MCP 操作（200）

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| action | string | 是 | 1–50 |
| character_id | int | 否 | >0 |
| novel_id | int | 否 | >0 |
| parameters | object | 否 | ≤50 键，序列化 ≤20000 |
| context | string | 否 | ≤4000 |

响应 `MCPCharacterResponse`：`success`、`action`、`character_id`、`result`、`message`、`timestamp`。错误：`404`/`422`/`500`。
### GET /api/characters/novel/{novel_id}/search — 搜索角色（200）
查询：`q`（必填，1–200）。响应：`{novel_id, search_term, characters, count}`。
## 六、生成（/api/generation）
### POST /api/generation/init — AI 初始化小说设定（200）

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| novel_id | int | 是 | >0 |
| target_chapters | int | 否 | 1–80，默认 10 |
| theme | string | 否 | ≤1000 |

响应 `InitNovelResponse`：`novel_id`、`worldview`、`main_characters`、`outline`、`plot_hooks`。错误：`404`、`422`、`500`。
### POST /api/generation/generate — 生成内容（200 → GenerationResponse）

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| novel_id | int | 是 | >0 |
| prompt | string | 是 | 1–4000 |
| chapter | int | 是 | >0 |
| current_day | int/null | 否 | >0，默认 null（未知）；未知时跳过按日检查 |
| target_length | int | 否 | 100–8000，默认 500 |

响应含 `final_content`、`agent_outputs[]`、`consistency_checks[]`、`retry_count`、`final_consistency`、`worldview_context[]`、`character_context[]`、`story_bible_context[]`、`context_manifest`、`rag_results[]`、`workflow_trace` 等。`story_bible_context` 为生成时实际读取且已裁剪的目标章有效事实 / 已发生事件。`context_manifest` 为共享上下文清单对象（schema 默认 `{}`），字段与边界见下文「共享上下文清单」；工作流检索步骤和 A/B/C 的 `data_sources.context_manifest` 保留相同清单。错误：`404`、`422` 提示词超预算、`500`。
### POST /api/generation/plot-options — 剧情走向选项（200）

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| novel_id | int | 是 | >0 |
| chapter_id | int | 是 | >0 |
| current_content | string | 是 | ≤50000 |
| num_options | int | 否 | 1–6，默认 3 |

响应：`{novel_id, chapter_id, options[]}`，`option` 含 `id`/`title`/`summary`/`impact`/`risk`。错误：`404`、`500`。
### POST /api/generation/auto-chapter — AI 自动生成并建章（200 → ChapterResponse）
章节号仍由服务端原子分配，不信任模型预测号。

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| novel_id | int | 是 | >0 |
| base_chapter_id | int | 否 | >0，不传用最后一章 |
| target_length | int | 否 | 100–3000，默认 500 |
| theme | string | 否 | ≤1000 |

错误：`404`、`409` 章节号冲突、`500`。
### POST /api/generation/rewrite — 局部改写（200 → RewriteResponse）

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| novel_id | int | 是 | >0 |
| chapter_id | int | 否 | >0 |
| original_text | string | 是 | 1–20000 |
| rewrite_type | string | 否 | `polish`/`rewrite`/`shorten`/`extend`，默认 `polish` |
| style_hint | string | 否 | ≤1000 |
| target_length | int | 否 | 10–5000 |

响应：`{rewritten_text}`。错误：`404`、`400` 原文不能为空、`500`。

工作台保存生成时的章节、全文与选区快照，展示只读原文和可编辑候选；采纳时正文必须与快照一致，且仅替换原选区。正文变化时禁用采纳，候选仍可复制。切换章节会取消请求并清理候选。客户端支持 `AbortSignal`，停止后不会采纳迟到响应；这不保证上游模型计算同时终止。
### POST /api/generation/continue — 章节续写（非流式，200）

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| novel_id | int | 是 | >0 |
| chapter_id | int | 是 | >0 |
| current_content | string | 是 | ≤50000 |
| target_length | int | 否 | 100–3000，默认 500 |
| current_day | int/null | 否 | >0，默认 null；未知时只按章节定位事件 |
| style_strength | float | 否 | 0–1，默认 0.7 |
| pace | string | 否 | `slow`/`medium`/`fast`，默认 `medium` |
| tone | string | 否 | `neutral`/`tense`/`relaxed`/`sad`/`joyful`，默认 `neutral` |
| use_rag_style | bool | 否 | 默认 true |
| style_sample_id | int | 否 | 可空 |
| plot_direction_hint | string | 否 | ≤600 |

响应 dict：`content`、`length`、`style_features[]`、`style_sample_id`、`rag_style_context[]`、`rag_story_context[]`、`agent_outputs[]`、`consistency_checks[]`、`retry_count`、`final_consistency`、`context_manifest`、`workflow_trace`、`settings{pace,tone,style_strength}`。`rag_story_context` 包含世界观/角色块与 Story Bible 上下文；L1 简介通过独立 Prompt 变量注入，来源清单由 `context_manifest` 返回。错误：`404`、`500`。
### POST /api/generation/continue-stream — 章节续写（SSE 流式）
请求字段同 `/continue`。响应 `Content-Type: text/event-stream`，`data:` 行为 JSON：

| type | 载荷 | 说明 |
|------|------|------|
| `metadata` | `data` | 与 `/continue` 对应的元数据，含 `context_manifest`；不含 `content`/`length`（一次） |
| `chunk` | `content` | 正文块（每块约 5 字符） |
| `done` | 无 | 完成 |
| `error` | `message` | 出错 |
| 其他 | `type`/`agent`/`status`/`data` | 转发各 Agent 中间事件 |

`metadata.data.context_manifest` 与本轮最终生成使用的共享包一致。上下文检索完成的 Agent 事件也携带 `data.context_manifest`；来源清单不是生成成功信号，客户端仍需等待 `done`。

取消：前端 `AbortSignal` → `reader.cancel()`；服务端 `http_request.is_disconnected()` 中止。HTTP 层错误：`404`、`500`；流内错误以 `error` 事件返回。
### POST /api/generation/outline — 生成大纲（200）
字段：`novel_id`（>0，必填）、`theme`（1–1000，必填）、`target_chapters`（1–80，默认 10）。响应：`{outline, chapters, context_manifest}`。
### POST /api/generation/character — 生成角色设定（200）
字段：`novel_id`（>0，必填）、`character_type`（1–20，必填）、`character_description`（1–1000，必填）。响应：`{character, type, context_manifest}`。
### GET /api/generation/test — 生成测试（仅 DEBUG）
非 DEBUG 返回 `404`。仍校验示例小说的作者归属；响应含 `final_content`、`length`、`context_manifest`。
## 七、审核（/api/review）
### POST /api/review/chapter — 章节全面审核（200）

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| novel_id | int | 是 | >0 |
| chapter_id | int | 是 | >0 |
| chapter_number | int | 是 | >0 |
| content | string | 是 | 1–50000 |
| previous_chapters | string[] | 否 | ≤3 项，每项 1–20000 |

响应 dict，至少含 `overall_score`、`is_ready_for_publish`、`review_status` 与 `pace_review`、`quality_review`、`plot_coherence`、`character_consistency`、`style_review`、`content_safety`（各维度嵌套结构待核对）。错误：`404`、`500`。
### POST /api/review/chapter-stream — 章节审核（SSE 流式）
请求字段同 `/chapter`。事件：

| type | 载荷 |
|------|------|
| `start` | `message` |
| `agent_result` | `agent`、`result`（agent ∈ pace/quality/plot/character/style/safety） |
| `summary` | 审核结果全量 |
| `done` | 无 |
| `error` | `message` |
### GET /api/review/test — 测试
需认证，响应 `{"status":"ok","message":"审核路由工作正常"}`。
## 八、一致性（/api/consistency）
### GET /api/consistency/test
需认证，响应 `{"status":"ok","message":"一致性检查路由工作正常"}`。
### POST /api/consistency/check-stream — 一致性检查（SSE 流式）

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| novel_id | int | 是 | >0 |
| chapter | int | 是 | >0（章节号） |
| content | string | 是 | 1–50000 |
| current_day | int/null | 否 | >0，默认 null（未知）；未知时跳过按日检查 |

事件由 `consistency_service.check_content_stream` 产出（事件类型待核对），末尾追加 `{type:"done"}`；出错 `{type:"error", message}`。HTTP 层错误：`404` 小说/章节不存在或无权访问。
## 九、RAG（/api/rag）
### POST /api/rag/debug — RAG 调试检索（200 → RAGResponse）

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| novel_id | int | 是 | >0 |
| query | string | 是 | 1–2000 |
| max_chapter | int | 否 | >0 |
| top_k | int | 否 | 1–20，默认 3 |

响应：`query`、`results[]`（`content`/`metadata`/`score`）、`retrieval_method`（当前实现固定为 `"vector_metadata"`，即纯向量 + 元数据过滤；`hybrid`/`bm25` 仅为历史注释，未实现）。错误：`404`。
### POST /api/rag/cleanup — 清理 RAG 数据（200）
字段：`novel_id`（int，必填）。响应：`{success, message, cleaned_items{vectors, graph_nodes, cache_entries}}`。错误：`404`、`500`。
## 十、风格（/api/style）
### POST /api/style/samples — 创建文风样本（201）

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| novel_id | int | 是 | >0 |
| name | string | 是 | 1–100 |
| sample_text | string | 是 | 1–100000 |

响应 `StyleSampleResponse`：`id`、`novel_id`、`name`、`sample_preview`（前 100 字符）、`style_features[]`、`created_at`。错误：`404`。
### GET /api/style/samples — 文风样本列表（200）
查询：`novel_id`（int，必填）。响应：`List[StyleSampleResponse]`。
## 十一、研究（/api/research）
### POST /api/research/search — 资料检索（200）
当前使用中文维基百科开放 API，后续可替换为 MCP 搜索（不改前端）。

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| novel_id | int | 否 | >0 |
| query | string | 是 | 1–500 |
| category | string | 否 | ≤50 |

响应 `ResearchResponse`：`query`、`results[]`（`title`/`summary`/`source`/`url`/`metadata`）。错误：`400` 检索问题不能为空、`500`。
## 十二、统一 MCP（/api/mcp）
### POST /api/mcp/execute — 执行统一 MCP 操作（200 → UnifiedMCPResponse）

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| target_type | string | 是 | 1–50 |
| action | string | 是 | 1–50 |
| target_id | int | 否 | >0 |
| novel_id | int | 否 | >0 |
| parameters | object | 否 | ≤50 键，序列化 ≤20000 |
| context | string | 否 | ≤4000 |
| ai_instructions | string | 否 | ≤2000 |

响应：`success`、`target_type`、`action`、`target_id`、`result`、`message`、`ai_reasoning`、`timestamp`、`workflow_trace`。错误：`501` 未实现、`500`。
### POST /api/mcp/analyze/novel — 全面分析小说（200）

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| novel_id | int | 是 | >0 |
| analysis_scope | string[] | 是 | 1–10 项，每项 1–50 |
| analysis_depth | string | 否 | 默认 `comprehensive`，1–50 |
| include_suggestions | bool | 否 | 默认 true |

响应 `NovelAnalysisResponse`：各维度分析、`overall_score`、`strengths`/`weaknesses`/`improvement_suggestions`、`workflow_trace` 等。错误：`404`、`501`、`500`。
### POST /api/mcp/optimize/novel — 全面优化小说（200）

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| novel_id | int | 是 | >0 |
| optimization_goals | string[] | 是 | 1–20 项，每项 1–500 |
| target_areas | string[] | 是 | 1–20 项，每项 1–50 |
| preserve_elements | string[] | 否 | ≤50 项，每项 1–500 |
| optimization_intensity | string | 否 | 默认 `moderate`，1–50 |

响应 `NovelOptimizationResponse`。错误：`404`、`501`、`500`。
### POST /api/mcp/ai-takeover/{novel_id} — AI 接管
请求体：`takeover_scope`（string[]）、`ai_instructions`（string，默认空）。**恒返回 `501`**（未接入可审计回滚链路）。
### POST /api/mcp/ai-autopilot/{novel_id} — 启用 AI 自动驾驶
请求体：`autopilot_config`（object）。**恒返回 `501`**（未实现调度/持久化/回滚）。
### GET /api/mcp/capabilities — 能力清单
无需认证。返回能力矩阵（以真实处理器为准，不承诺占位功能）。
### 审计端点组（/api/mcp/audit/*）

| 端点 | 认证 | 参数 |
|------|------|------|
| `GET /api/mcp/audit/history` | 是 | `limit`（1–500，默认 50）、`target_type`、`action`、`success_only` |
| `GET /api/mcp/audit/novel/{novel_id}/history` | 是 | `limit`（1–500，默认 100） |
| `GET /api/mcp/audit/statistics` | 是 | `days`（1–365，默认 30） |
| `GET /api/mcp/audit/novel/{novel_id}/statistics` | 是 | `days`（1–365，默认 30） |
| `GET /api/mcp/audit/errors` | 是 | `days`（1–365，默认 7） |
| `GET /api/mcp/monitoring/performance` | 是 | 无 |

审计响应：`history` → `{user_id, total_records, operations[]}`，`operation` 含 `id`/`target_type`/`action`/`novel_id`/`target_id`/`success`/`execution_time_ms`/`ai_tokens_used`/`created_at`/`error_message`；`statistics` → `{statistics}`；`errors` → `{error_analysis}`。
## 十三、Story Bible（/api/story-bible）

结构化事实账本与剧情事件基础接口。写入模型均拒绝未知字段；所有资源先校验小说归属，越权统一返回 `404`。生成工作流会读取目标章当时有效的事实（包括退役章晚于目标章的历史事实），以及在目标章/已知故事日范围内的 occurred 事件，planned 事件不注入。故事日未知且有限定章节时，未定位章节的事件不自动召回；故事日明确时可召回日期不晚于该日的无章事件。所有内容经统一预算裁剪后注入 Agent A/B/C。

### 事实账本（facts）

#### POST /api/story-bible/facts — 创建事实（201 → FactResponse）

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| novel_id | int | 是 | >0 |
| subject | string | 是 | 1–100 |
| attribute | string | 是 | 1–100 |
| value | string | 是 | 1–2000 |
| description | string | 否 | ≤4000 |
| chapter_established | int | 否 | >0 |

创建状态固定为 `active`。响应 `FactResponse`：`id`、`novel_id`、`subject`、`attribute`、`value`、`description`、`chapter_established`、`status`、`retired_chapter`、`created_at`、`updated_at`。错误：`404` 小说不存在或无权访问、`422` 校验失败。

#### GET /api/story-bible/facts — 事实列表（200 → List[FactResponse]）

查询：`novel_id`（必填，>0）、`status_filter`（可选，`active`/`retired`）、`skip`（≥0，默认 0）、`limit`（1–100，默认 100）。错误：`404`、`422` 非法状态值。

#### GET /api/story-bible/facts/{fact_id} — 事实详情（200 → FactResponse）

错误：`404` 事实不存在或无权访问。

#### PUT /api/story-bible/facts/{fact_id} — 更新事实（200 → FactResponse）

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| value | string | 否 | 1–2000 |
| description | string | 否 | ≤4000 |
| chapter_established | int | 否 | >0 |
| status | string | 否 | `active`/`retired` |
| retired_chapter | int | 否 | >0 |

除 `retired_chapter` 外的至少一个业务字段必填；空对象返回 `422`。状态流转为 `retired` 且未传 `retired_chapter` 时，服务端默认沿用 `chapter_established`。错误：`404`、`422`。

#### DELETE /api/story-bible/facts/{fact_id} — 删除事实（204）

错误：`404` 事实不存在或无权访问。

### 剧情事件（events）

#### POST /api/story-bible/events — 创建剧情事件（201 → EventResponse）

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| novel_id | int | 是 | >0 |
| title | string | 是 | 1–200 |
| description | string | 是 | 1–8000 |
| story_day | int | 否 | >0，默认 1 |
| chapter | int | 否 | >0 |
| involved_characters | string[] | 否 | ≤50 项，每项 1–100 |
| foreshadowing | string | 否 | ≤4000 |
| status | string | 否 | `planned`/`occurred`，默认 `planned` |

响应 `EventResponse`：`id`、`novel_id`、`title`、`description`、`story_day`、`chapter`、`involved_characters`、`foreshadowing`、`status`、`created_at`、`updated_at`。错误：`404`、`422`。

#### GET /api/story-bible/events — 事件列表（200 → List[EventResponse]）

查询：`novel_id`（必填，>0）、`status_filter`（可选，`planned`/`occurred`）、`skip`（≥0，默认 0）、`limit`（1–100，默认 100）。列表按 `story_day`、`id` 升序。错误：`404`、`422`。

#### GET /api/story-bible/events/{event_id} — 事件详情（200 → EventResponse）

错误：`404` 事件不存在或无权访问。

#### PUT /api/story-bible/events/{event_id} — 更新事件（200 → EventResponse）

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| title | string | 否 | 1–200 |
| description | string | 否 | 1–8000 |
| story_day | int | 否 | >0 |
| chapter | int | 否 | >0 |
| involved_characters | string[] | 否 | ≤50 项，每项 1–100 |
| foreshadowing | string | 否 | ≤4000 |
| status | string | 否 | `planned`/`occurred` |

至少提供一个业务字段；空对象返回 `422`。错误：`404`、`422`。

#### DELETE /api/story-bible/events/{event_id} — 删除事件（204）

错误：`404` 事件不存在或无权访问。
## 十四、SSE 客户端约定（依据 frontend/lib/sse.ts）

- 服务端 `Content-Type: text/event-stream`，事件为 `data: <JSON>\n\n`。
- 客户端按 `\r?\n\r?\n` 切块，取 `data:` 行拼接后 `JSON.parse`。
- 事件类型识别：`chunk`（正文）、`metadata`、`done`（成功结束）、`error`（抛错）。
- **未收到 `done` 而流中断 → 抛 `SSEUnexpectedEOFError`**，避免断网误判成功。
- 取消：`AbortSignal` → `reader.cancel()`；服务端在断连检查点中止响应，不保证已经发往模型服务的计算同步停止。
## 十五、与旧版文档的主要差异

1. **新增 8+ 模块端点**：角色、生成（init/generate/plot-options/auto-chapter/rewrite/continue/outline/character）、审核、一致性、RAG、风格、研究、统一 MCP，及健康检查 `/api/health`、`/api/ping`。旧文档仅覆盖认证/小说/章节。

2. **章节号分配改变**：新增 `POST /api/novels/{novel_id}/chapters/next`，由**服务端原子分配**「最大章号 + 1」；旧文档要求客户端自选 `chapter_number`。

3. **章节更新引入乐观锁**：`PUT .../chapters/{chapter_id}` **必须**携带 `expected_version`；版本冲突 `409`（`detail` 带当前版本号）。旧文档「所有字段可选」已过时。

4. **章节列表形态改变**：由「含正文数组」改为**分页对象** `{items,total,page,page_size,has_more}`，`items` 为摘要（不含 `content`），正文按章号取详情。

5. **新增 SSE 流式端点**：`/generation/continue-stream`、`/review/chapter-stream`、`/consistency/check-stream`，明确事件名与客户端取消语义。

6. **基址调整**：旧文档 `http://localhost:8000`，前端实际默认 `http://127.0.0.1:8000/api`（`NEXT_PUBLIC_API_BASE` 可覆盖）。

7. **新增聚合统计**：`GET /api/novels/statistics` 一次返回全部小说章节数与总字数。

8. **章节响应新增字段**：`ChapterResponse` 现含 `version`（乐观锁版本）与 `word_count`。

9. **明确 501 语义**：MCP 未实现能力（`ai-takeover`、`ai-autopilot`）明确返回 `501`，不再提供占位成功结果。

10. **新增 Story Bible 基础接口**：`/api/story-bible/facts` 与 `/api/story-bible/events` CRUD 已上线，写入预算与小说归属校验已补齐；角色已有独立管理，地点、大纲等其余结构化模型仍不在当前能力范围。


## 十六、创作对话（/api/writing-chat）

所有接口验证小说所有权；无权访问与不存在均返回 `404`。对话不会自动写入章节。

### GET /api/writing-chat/{novel_id}/turns

查询参数：`limit`（1–100，默认 30）、`before`（可选，正整数记录 ID）。返回最新一页，以 ID 升序排列；传当前页最小 ID 可加载更早历史。过期未完成请求标记失败。

### POST /api/writing-chat/{novel_id}/turns

请求字段：`request_id`（UUID，同小说内幂等）、`chapter_id`（所属章节）、`mode`（`discuss`/`continue`，默认讨论）、`message`（非空，最多 4000 字符）、`current_content`（编辑器快照，最多 50000 字符）。问题先落库，模型完成且通过输出契约后返回完整记录；失败也保留问题并返回 `failed` 状态；此类模型执行失败仍可返回 HTTP 200，客户端必须检查业务 `status`。

记录包含 `id`、`request_id`、`novel_id`、`chapter_id`、`chapter_title`、`mode`、`user_text`、`assistant_text`、`base_content_hash`（UTF-8 正文 SHA-256）、`status`（`pending`/`completed`/`failed`/`cancelled`）、`error`、`context_manifest`（object/null）、`created_at`。客户端可轮询列表恢复未完成请求状态。重复请求 ID 返回原记录，失败后重新发送使用新 UUID。

### POST /api/writing-chat/{novel_id}/turns/{request_id}/stop

将尚未完成的记录标为 `cancelled`，返回记录；已完成记录保持原样。尚未落库返回 `404`。停止后迟到的模型响应不能写成成功回复，但不保证模型服务停止计算。

模型上下文：最近最多 20 个已完成轮次，并限制历史总计 8000 字符；世界观、事实/事件与正文分别沿用统一预算。较早记录仍可在界面查看，但不承诺每轮全部注入。

### 共享上下文清单（context_manifest）

创作对话与高级生成通过同一 `ContextPack` 构建器读取作者世界观、已确认事实/事件及 L1 前章简介。作者 ID 与小说生命周期由服务端确定，不接受客户端作为生成请求的可信字段。L1 只选严格早于目标章节、当前原文版本、当前提取配方且 `ready` 的简介；同时复核作品/章节生命周期、原文哈希与逐字引用。当前章、未来章、旧稿和旧配方简介不注入，`state_change_candidates` 不作为确认事实注入。

| 清单字段 | 类型 | 含义 |
|---|---|---|
| `version` | int | 当前协议版本为 `1` |
| `scope` | object | `novel_id`、`novel_lifecycle_id`、`target_chapter`、`current_day`（int/null）、`memory_head_version` |
| `sources` | object[] | 仅本轮实际注入的 L1 简介来源，按章序排列；不枚举正文、对话历史、Story Bible 或向量片段 |
| `warnings` | string[] | 无有效简介、来源校验失败、扫描或预算限制、简介存储不可用等说明 |
| `omitted` | object | 省略/裁剪原因到计数的映射；可能含 `digest_limit`、`context_budget`、`summary_trimmed`、`invalid_source`、`scan_window_at_least`，不是全书缺失简介统计 |
| `fingerprint` | string | SHA-256，绑定清单及共享包中的世界观、事实/事件、实际简介文本；不包含当前指令、编辑器快照、历史问答、RAG 或 Agent 中间输出，不是完整模型输入指纹 |

每个 `sources` 元素含 `kind`（固定 `chapter_digest`）、`id`（简介 ID）、`title`、`chapter_id`、`chapter_number`、`source_revision_id`、`source_version`、`content_hash`（来源原文 SHA-256）。可用原文版本 API 按 `source_revision_id` 只读核对来源；清单不直接携带全文。

召回优先选最近的有效前章，最多 **3 章**；每条简介最多 **700 字符**，简介整体最多 **2400 字符**（含标题与参考性质说明）。来源与裁剪后的实际注入条目对应，模型节点不再二次截断简介。最多核验最近 50 条候选，窗口外仅报告至少还有候选未扫描。没有可用简介或简介存储异常时，`sources=[]` 并附说明，仍可使用原文和作者确认设定；作者或生命周期验证失败则停止生成。

新 `WritingTurn` 在 `pending` 落库时冻结本轮清单，GET、重复 UUID、失败及取消均返回该轮原清单，之后章节改稿或重建简介不会重算历史清单。升级前的历史轮次返回 `context_manifest=null`，表示当时未记录来源；它与新轮次 `sources=[]` 的“本轮未使用 L1”含义不同。

启动升级代码前备份数据库，并在 `backend` 目录执行 `.venv/bin/python init_db.py`，应用当前 Alembic head `e2b6c8d0f345`（依次经过 `b9e3f5a7c012`、`c0f4a6b8d123`、`d1a5b7c9e234`）。后续迁移增加来源清单、结构化状态、候选执行与持久投影任务，不回填或改写旧问答；回退前须导出新增派生与审计数据。

### 已确认剧情的上下文边界

创作对话和高级生成共用 Story Bible 查询：不晚于目标章节确立且在该章仍有效的事实可进入上下文；已退役事实在明确失效章之前仍可用于回写旧章，失效章起排除。没有目标章节时只取当前 active 事实。事件只取 occurred，planned 仍可通过账本 CRUD 管理，但不会被当作已发生剧情注入。

一致性 HTTP/SSE 遇到未加载可执行规则或已确认时间线时，相关层返回 skipped 和原因，不标记检查通过。此行为不代表数据库账本已自动接入一致性服务，当前接线缺口见架构评审。

模型输出异常：共享解析器拒绝提供方报告的截断/过滤/工具调用、非文本、空文本和超过 20000 字符的回复。创作对话保存 failed 与中文原因，不返回可采纳的半段正文；模型超时也有明确失败原因。高级生成的普通请求走现有错误响应，SSE 走 error 事件；六维审核失败不允许发布。提供方缺失完成元数据时兼容文本输出，不推测 token 用量。

## 原文版本与章节简介（M1）

全部要求 Bearer JWT。小说、章节、原文版本、任务不属于当前作者或生命周期不匹配均返回 404。保存正文的现有 API 契约不变，服务端同事务写原文版本与简介任务；请求不等待模型。L0/L1 三表由迁移 `a8d2e4f6b901` 引入；当前版本还需运行 `init_db.py` 应用至当前 head `e2b6c8d0f345`，详见上文共享清单迁移说明。

| 端点 | 返回 |
|---|---|
| `GET /api/novels/{novel_id}/chapters/{chapter_id}/digest` | 200，`{status,current_version,worker_enabled,digest,job}` |
| `POST /api/novels/{novel_id}/chapters/{chapter_id}/digest/rebuild` | 202，任务对象；无请求体，仅使用已保存正文 |
| `GET /api/novels/{novel_id}/chapters/{chapter_id}/revisions` | 200，版本摘要数组，倒序；limit 默认20最大100，before_version 正整数可选 |
| `GET /api/novels/{novel_id}/revisions/{revision_id}` | 200，版本摘要加 `chapter_id,content`，UUID 来源 ID |
| `GET /api/memory-jobs/{job_id}` | 200，任务对象，UUID ID |

简介状态 `ready/stale/missing` 与任务状态独立。digest 可为 null，非空时含 `id,source_revision_id,source_version,summary,participants,events,state_change_candidates,open_threads,source_refs,created_at`；四类列表均为有界字符串。source_refs 含 `revision_id,start,end,quote,content_hash,quote_hash`，位置为 Python Unicode 字符索引、end 不包含；content_hash 为完整原文 SHA-256，quote_hash 为引用片段 SHA-256，来源身份由服务器生成。

任务对象含 `id,state,attempts,max_attempts,error_code,error_message`。状态为 queued/running/succeeded/failed/cancelled/superseded，并提供任务查询、重建和取消 API。相同版本/配方重建复用同任务，已经成功的任务不重复调用模型；failed/cancelled/superseded 的显式重建将同一任务重新排队并重置本轮尝试。来源在重建竞争中变化返回409；空白或超过20000字符的整章来源返回422。

worker_enabled 默认为 false，排队不代表模型正在执行；实际启用说明见 QUICKSTART。简介中的状态变化仍为候选，不会写 StoryFact。旧简介可返回 stale 供只读核对，不能当成当前事实。ContextPack 的 `memory_head_version` 在候选保存前会再次校验，记忆变化时旧候选返回 409；版本摘要含 `id,version,chapter_number,title,content_hash,created_at`。一键恢复、跨全书语义召回和场景级时间锚点暂未提供。
