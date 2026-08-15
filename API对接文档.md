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
### PUT /api/novels/{novel_id} — 更新（200 → NovelResponse）
字段（全可选，至少一项否则 422）：`title`(1–200)、`genre`(≤50)、`description`(≤8000)、`worldview`(≤50000)，均可传 null 清空。错误：`404`、`403` 无权修改此小说、`422` 空更新。
### DELETE /api/novels/{novel_id} — 删除（204）
级联删除章节，RAG 派生索引后台清理。错误：`404`、`403`、`500`。
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
| current_day | int | 否 | >0，默认 1 |
| target_length | int | 否 | 100–8000，默认 500 |

响应含 `final_content`、`agent_outputs[]`、`consistency_checks[]`、`retry_count`、`final_consistency`、`worldview_context[]`、`character_context[]`、`rag_results[]`、`workflow_trace` 等。错误：`404`、`422` 提示词超预算、`500`。
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
### POST /api/generation/continue — 章节续写（非流式，200）

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| novel_id | int | 是 | >0 |
| chapter_id | int | 是 | >0 |
| current_content | string | 是 | ≤50000 |
| target_length | int | 否 | 100–3000，默认 500 |
| style_strength | float | 否 | 0–1，默认 0.7 |
| pace | string | 否 | `slow`/`medium`/`fast`，默认 `medium` |
| tone | string | 否 | `neutral`/`tense`/`relaxed`/`sad`/`joyful`，默认 `neutral` |
| use_rag_style | bool | 否 | 默认 true |
| style_sample_id | int | 否 | 可空 |
| plot_direction_hint | string | 否 | ≤600 |

响应 dict：`content`、`length`、`style_features[]`、`style_sample_id`、`rag_style_context[]`、`rag_story_context[]`、`agent_outputs[]`、`consistency_checks[]`、`retry_count`、`final_consistency`、`workflow_trace`、`settings{pace,tone,style_strength}`。错误：`404`、`500`。
### POST /api/generation/continue-stream — 章节续写（SSE 流式）
请求字段同 `/continue`。响应 `Content-Type: text/event-stream`，`data:` 行为 JSON：

| type | 载荷 | 说明 |
|------|------|------|
| `metadata` | `data` | 与 `/continue` 响应同结构元数据（一次） |
| `chunk` | `content` | 正文块（每块约 5 字符） |
| `done` | 无 | 完成 |
| `error` | `message` | 出错 |
| 其他 | `type`/`agent`/`status`/`data` | 转发各 Agent 中间事件 |

取消：前端 `AbortSignal` → `reader.cancel()`；服务端 `http_request.is_disconnected()` 中止。HTTP 层错误：`404`、`500`；流内错误以 `error` 事件返回。
### POST /api/generation/outline — 生成大纲（200）
字段：`novel_id`（>0，必填）、`theme`（1–1000，必填）、`target_chapters`（1–80，默认 10）。响应：`{outline, chapters}`。
### POST /api/generation/character — 生成角色设定（200）
字段：`novel_id`（>0，必填）、`character_type`（1–20，必填）、`character_description`（1–1000，必填）。响应：`{character, type}`。
### GET /api/generation/test — 生成测试（仅 DEBUG）
非 DEBUG 返回 `404`。响应含 `final_content`、`length`。
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
| current_day | int | 否 | >0，默认 1 |

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

结构化事实账本与剧情事件基础接口。写入模型均拒绝未知字段；所有资源先校验小说归属，越权统一返回 `404`。

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
- 取消：`AbortSignal` → `reader.cancel()`；服务端 `is_disconnected()` 检测后中止。
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
