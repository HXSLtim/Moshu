import Schema from '@deepseek-ai/schemastery'
import { defineTool } from '@deepseek-ai/dsh-tools'

export const name = 'dsh-nai'
export const inject = ['tools']

/**
 * 插件配置。token 留空时只调用不需要认证的健康检查与能力清单。
 */
export const Config = Schema.object({
  apiBase: Schema.string().default('http://127.0.0.1:8000/api'),
  token: Schema.string().default(''),
  timeoutMs: Schema.number().default(60_000),
})

function normalizeBase(value) {
  return String(value || 'http://127.0.0.1:8000/api').replace(/\/+$/, '')
}

function buildUrl(base, path, params = {}) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') {
      query.set(key, String(value))
    }
  }
  const suffix = query.size > 0 ? `?${query.toString()}` : ''
  return `${base}${path}${suffix}`
}

export class NaiApiError extends Error {
  constructor(message, status, payload) {
    super(message)
    this.name = 'NaiApiError'
    this.status = status
    this.payload = payload
  }
}

export function createClient(config) {
  const base = normalizeBase(config?.apiBase)
  const token = String(config?.token || '')
  const timeoutMs = Number(config?.timeoutMs ?? 60_000)

  async function request(path, { method = 'GET', params, body, signal, includeResponse = false } = {}) {
    const controller = new AbortController()
    const timer = setTimeout(
      () => controller.abort(new Error(`Nai API 请求超时（${timeoutMs}ms）`)),
      timeoutMs,
    )
    const forwardAbort = () => controller.abort(signal?.reason)
    if (signal?.aborted) {
      forwardAbort()
    } else {
      signal?.addEventListener('abort', forwardAbort, { once: true })
    }

    try {
      const response = await fetch(buildUrl(base, path, params), {
        method,
        signal: controller.signal,
        headers: {
          Accept: 'application/json',
          ...(body ? { 'Content-Type': 'application/json' } : {}),
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        ...(body ? { body: JSON.stringify(body) } : {}),
      })

      let payload = null
      if (response.status !== 204 && method !== 'HEAD') {
        try {
          payload = await response.json()
        } catch {
          if (response.ok) throw new Error('Nai API 返回了无效 JSON')
        }
      }
      if (!response.ok) {
        let detail = `Nai API 返回 ${response.status}`
        if (typeof payload?.detail === 'string') {
          detail = payload.detail
        } else if (Array.isArray(payload?.detail)) {
          detail = payload.detail
            .map((issue) => `${issue.loc?.join('.') || '请求体'}: ${issue.msg}`)
            .join('; ')
        }
        throw new NaiApiError(detail, response.status, payload)
      }
      return includeResponse ? { status: response.status, payload } : payload
    } finally {
      clearTimeout(timer)
      signal?.removeEventListener('abort', forwardAbort)
    }
  }

  return { request }
}

function renderJson(_args, value) {
  return [{ type: 'text', text: JSON.stringify(value, null, 2) }]
}

const JSON_OUTPUT = {
  schema: { type: 'json' },
  render: renderJson,
}

export function apply(ctx, config = {}) {
  const { request } = createClient(config)

  ctx.tools.register(defineTool({
    name: 'nai_health',
    description: '检查 Nai 小说写作服务是否在线，返回服务名与版本。',
    parameters: {},
    output: JSON_OUTPUT,
    async execute(_args) {
      return request('/health')
    },
  }))

  ctx.tools.register(defineTool({
    name: 'nai_novels_list',
    description:
      '列出当前作者的全部小说，返回小说 ID、标题、类型与简介。先调用它拿到 novel_id，再调用其他按小说操作的 Nai 工具。',
    parameters: {
      skip: { type: 'integer', description: '跳过条数，默认 0。' },
      limit: { type: 'integer', description: '返回条数，默认 100。' },
    },
    output: JSON_OUTPUT,
    async execute(args, exec) {
      return request('/novels', {
        params: args,
        signal: exec.signal,
      })
    },
  }))

  ctx.tools.register(defineTool({
    name: 'nai_novel_create',
    description:
      '创建一部 Nai 小说，返回新小说的 novel_id。创建后仍需由作者确认章节内容，AI 不能把未确认草稿直接写成正式正文。',
    parameters: {
      title: {
        type: 'string',
        required: true,
        description: '小说标题，1-200 字符。',
      },
      genre: { type: 'string', description: '小说类型，最长 50 字符。' },
      description: { type: 'string', description: '小说简介，最长 8000 字符。' },
      worldview: { type: 'string', description: '世界观设定，最长 50000 字符。' },
    },
    output: JSON_OUTPUT,
    async execute(args, exec) {
      return request('/novels', {
        method: 'POST',
        body: args,
        signal: exec.signal,
      })
    },
  }))

  ctx.tools.register(defineTool({
    name: 'nai_novel_get',
    description:
      '读取一部 Nai 小说的详情，包括标题、类型、简介与世界观设定。',
    parameters: {
      novel_id: {
        type: 'integer',
        required: true,
        description: '小说 ID，必须大于 0。',
      },
    },
    output: JSON_OUTPUT,
    async execute(args, exec) {
      const { novel_id } = args
      return request(`/novels/${novel_id}`, {
        signal: exec.signal,
      })
    },
  }))

  ctx.tools.register(defineTool({
    name: 'nai_characters_list',
    description:
      '列出 Nai 小说的角色档案。角色是 Story Bible 的一部分，可用于生成前的上下文核对。',
    parameters: {
      novel_id: {
        type: 'integer',
        required: true,
        description: '小说 ID，必须大于 0。',
      },
      skip: { type: 'integer', description: '跳过条数，默认 0。' },
      limit: { type: 'integer', description: '返回条数，默认 100，最大 100。' },
      importance_level: {
        type: 'string',
        enum: ['main', 'secondary', 'minor'],
        description: '按角色重要性过滤，可选。',
      },
    },
    output: JSON_OUTPUT,
    async execute(args, exec) {
      const { novel_id, ...params } = args
      return request(`/characters/novel/${novel_id}`, {
        params,
        signal: exec.signal,
      })
    },
  }))

  ctx.tools.register(defineTool({
    name: 'nai_story_facts_list',
    description:
      '列出 Nai 小说的 Story Bible 事实账本。只返回作者已确认且当前 active 或指定状态的事实。',
    parameters: {
      novel_id: {
        type: 'integer',
        required: true,
        description: '小说 ID，必须大于 0。',
      },
      status_filter: {
        type: 'string',
        enum: ['active', 'retired'],
        description: '默认只列出 active 事实。',
      },
      skip: { type: 'integer', description: '跳过条数，默认 0。' },
      limit: { type: 'integer', description: '返回条数，默认 100，最大 100。' },
    },
    output: JSON_OUTPUT,
    async execute(args, exec) {
      return request('/story-bible/facts', {
        params: args,
        signal: exec.signal,
      })
    },
  }))

  ctx.tools.register(defineTool({
    name: 'nai_story_events_list',
    description:
      '列出 Nai 小说的 Story Bible 剧情事件，按故事天数升序返回。',
    parameters: {
      novel_id: {
        type: 'integer',
        required: true,
        description: '小说 ID，必须大于 0。',
      },
      status_filter: {
        type: 'string',
        enum: ['planned', 'occurred'],
        description: '事件状态：planned 或 occurred。',
      },
      skip: { type: 'integer', description: '跳过条数，默认 0。' },
      limit: { type: 'integer', description: '返回条数，默认 100，最大 100。' },
    },
    output: JSON_OUTPUT,
    async execute(args, exec) {
      return request('/story-bible/events', {
        params: args,
        signal: exec.signal,
      })
    },
  }))

  ctx.tools.register(defineTool({
    name: 'nai_story_fact_create',
    description:
      '在 Nai 小说的 Story Bible 中创建一条作者已确认的事实，创建后状态固定为 active。',
    parameters: {
      novel_id: {
        type: 'integer',
        required: true,
        description: '所属小说 ID，必须大于 0。',
      },
      subject: {
        type: 'string',
        required: true,
        description: '事实主体，如角色名、地点或组织名，1-100 字符。',
      },
      attribute: {
        type: 'string',
        required: true,
        description: '事实属性，如身份、位置、持有物，1-100 字符。',
      },
      value: {
        type: 'string',
        required: true,
        description: '事实值，1-2000 字符。',
      },
      description: {
        type: 'string',
        description: '补充说明，最长 4000 字符。',
      },
      chapter_established: {
        type: 'integer',
        description: '确立该事实的章节号，不填表示全书通用。',
      },
    },
    output: JSON_OUTPUT,
    async execute(args, exec) {
      return request('/story-bible/facts', {
        method: 'POST',
        body: args,
        signal: exec.signal,
      })
    },
  }))

  ctx.tools.register(defineTool({
    name: 'nai_story_fact_update',
    description:
      '更新 Nai 小说的 Story Bible 事实，可流转为 retired 并记录失效章节。',
    parameters: {
      fact_id: {
        type: 'integer',
        required: true,
        description: '事实 ID，必须大于 0。',
      },
      value: { type: 'string', description: '新事实值，1-2000 字符。' },
      description: { type: 'string', description: '新补充说明，最长 4000 字符。' },
      chapter_established: {
        type: 'integer',
        description: '重新指定确立章节号。',
      },
      status: {
        type: 'string',
        enum: ['active', 'retired'],
        description: '状态；retired 表示该事实已失效但保留历史。',
      },
      retired_chapter: {
        type: 'integer',
        description: '失效章节号；不填时默认沿用确立章节。',
      },
    },
    output: JSON_OUTPUT,
    async execute(args, exec) {
      const { fact_id, ...body } = args
      return request(`/story-bible/facts/${fact_id}`, {
        method: 'PUT',
        body,
        signal: exec.signal,
      })
    },
  }))

  ctx.tools.register(defineTool({
    name: 'nai_story_event_create',
    description:
      '在 Nai 小说的 Story Bible 中创建一个剧情事件，可记录伏笔。',
    parameters: {
      novel_id: {
        type: 'integer',
        required: true,
        description: '所属小说 ID，必须大于 0。',
      },
      title: {
        type: 'string',
        required: true,
        description: '事件标题，1-200 字符。',
      },
      description: {
        type: 'string',
        required: true,
        description: '事件描述，1-8000 字符。',
      },
      story_day: {
        type: 'integer',
        description: '故事内天数，默认 1。',
      },
      chapter: {
        type: 'integer',
        description: '对应章节号，可不填。',
      },
      involved_characters: {
        type: 'array',
        items: { type: 'string' },
        description: '关联角色名列表，最多 50 项。',
      },
      foreshadowing: {
        type: 'string',
        description: '该事件埋下的伏笔或线索，最长 4000 字符。',
      },
      status: {
        type: 'string',
        enum: ['planned', 'occurred'],
        description: 'planned 或 occurred，默认 planned。',
      },
    },
    output: JSON_OUTPUT,
    async execute(args, exec) {
      return request('/story-bible/events', {
        method: 'POST',
        body: args,
        signal: exec.signal,
      })
    },
  }))

  ctx.tools.register(defineTool({
    name: 'nai_chapters_list',
    description:
      '列出 Nai 小说的章节摘要。摘要不含正文，避免一次把全书正文读入上下文。',
    parameters: {
      novel_id: {
        type: 'integer',
        required: true,
        description: '小说 ID，必须大于 0。',
      },
      page: { type: 'integer', description: '页码，默认 1。' },
      page_size: { type: 'integer', description: '每页条数，默认 50，最大 100。' },
    },
    output: JSON_OUTPUT,
    async execute(args, exec) {
      const { novel_id, page, page_size } = args
      return request(`/novels/${novel_id}/chapters`, {
        params: { page, page_size },
        signal: exec.signal,
      })
    },
  }))

  ctx.tools.register(defineTool({
    name: 'nai_chapter_get',
    description:
      '按 chapter_id 读取 Nai 小说的单个章节正文与版本号。正文可能很长，只应在需要逐字阅读或准备保存时按需调用；保存前以返回的 version 作为 expected_version。',
    parameters: {
      novel_id: {
        type: 'integer',
        required: true,
        description: '小说 ID，必须大于 0。',
      },
      chapter_id: {
        type: 'integer',
        required: true,
        description: '章节 ID，必须大于 0。',
      },
    },
    output: JSON_OUTPUT,
    async execute(args, exec) {
      const { novel_id, chapter_id } = args
      return request(`/novels/${novel_id}/chapters/${chapter_id}`, {
        signal: exec.signal,
      })
    },
  }))

  ctx.tools.register(defineTool({
    name: 'nai_chapter_create_next',
    description:
      '为 Nai 小说创建下一章，章节号由服务端原子分配。可同时写入标题与正文；正文为空时只建空章，后续用 nai_chapter_update 保存。',
    parameters: {
      novel_id: {
        type: 'integer',
        required: true,
        description: '小说 ID，必须大于 0。',
      },
      title: { type: 'string', description: '章节标题，1-200 字符。' },
      content: { type: 'string', description: '章节正文，最长 500000 字符。' },
    },
    output: JSON_OUTPUT,
    async execute(args, exec) {
      const { novel_id, ...body } = args
      return request(`/novels/${novel_id}/chapters/next`, {
        method: 'POST',
        body,
        signal: exec.signal,
      })
    },
  }))

  ctx.tools.register(defineTool({
    name: 'nai_chapter_update',
    description:
      '保存 Nai 小说的章节正文或标题，必须携带章节 version、章节 rag_lifecycle_id 与所属小说 rag_lifecycle_id。版本或生命周期冲突返回 409，须重新读取并由作者核对，不能把已删除作品的旧稿写入同 ID 新作品。',
    parameters: {
      novel_id: {
        type: 'integer',
        required: true,
        description: '小说 ID，必须大于 0。',
      },
      chapter_id: {
        type: 'integer',
        required: true,
        description: '章节 ID，必须大于 0。',
      },
      expected_version: {
        type: 'integer',
        required: true,
        description: '上次读取到的章节 version，必须大于等于 1。',
      },
      expected_novel_lifecycle_id: {
        type: 'string', required: true,
        description: 'nai_novel_get 返回的 rag_lifecycle_id，32 字符。',
      },
      expected_chapter_lifecycle_id: {
        type: 'string', required: true,
        description: 'nai_chapter_get 返回的 rag_lifecycle_id，32 字符。',
      },
      chapter_number: {
        type: 'integer',
        description: '可选的新章节号，大于 0。',
      },
      title: { type: 'string', description: '可选的新标题，1-200 字符。' },
      content: { type: 'string', description: '可选的新正文，最长 500000 字符。' },
    },
    output: JSON_OUTPUT,
    async execute(args, exec) {
      const { novel_id, chapter_id, ...body } = args
      return request(`/novels/${novel_id}/chapters/${chapter_id}`, {
        method: 'PUT',
        body,
        signal: exec.signal,
      })
    },
  }))

  ctx.tools.register(defineTool({
    name: 'nai_generation_generate',
    description:
      '调用 Nai 的多 Agent 工作流生成小说正文候选。生成结果只作为候选，不会自动写入章节；响应包含最终使用的 Story Bible 上下文。',
    parameters: {
      novel_id: {
        type: 'integer',
        required: true,
        description: '小说 ID，必须大于 0。',
      },
      prompt: {
        type: 'string',
        required: true,
        description: '剧情提示词，1-4000 字符。',
      },
      chapter: {
        type: 'integer',
        required: true,
        description: '目标章节号，必须大于 0。',
      },
      current_day: {
        type: 'integer',
        description: '故事当前天数，默认 1。',
      },
      target_length: {
        type: 'integer',
        description: '目标字数，100-8000，默认 500。',
      },
    },
    output: JSON_OUTPUT,
    async execute(args, exec) {
      return request('/generation/generate', {
        method: 'POST',
        body: args,
        signal: exec.signal,
      })
    },
  }))
}
