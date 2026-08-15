import test from 'node:test'
import assert from 'node:assert/strict'
import { apply } from '../index.js'

function createHarnessContext() {
  const tools = []
  return {
    tools,
    ctx: {
      tools: {
        register(definition) {
          tools.push(definition)
        },
      },
    },
  }
}

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

test('注册 Nai 工具清单', () => {
  const { ctx, tools } = createHarnessContext()
  apply(ctx, { apiBase: 'http://nai.test/api', token: '', timeoutMs: 1000 })

  assert.deepEqual(
    tools.map((tool) => tool.name),
    [
      'nai_health',
      'nai_story_facts_list',
      'nai_story_events_list',
      'nai_story_fact_create',
      'nai_story_fact_update',
      'nai_story_event_create',
      'nai_chapters_list',
      'nai_generation_generate',
    ],
  )
})

test('健康检查工具返回后端 JSON', async () => {
  const { ctx, tools } = createHarnessContext()
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (url) => {
    assert.equal(url, 'http://nai.test/api/health')
    return jsonResponse({ status: 'healthy', app_name: 'Nai', version: '0.1.0' })
  }
  try {
    apply(ctx, { apiBase: 'http://nai.test/api', token: '', timeoutMs: 1000 })
    const health = tools.find((tool) => tool.name === 'nai_health')
    const value = await health.execute({}, { signal: undefined })
    assert.deepEqual(value, { status: 'healthy', app_name: 'Nai', version: '0.1.0' })
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('事实列表携带 Bearer token 与查询参数', async () => {
  const { ctx, tools } = createHarnessContext()
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (url, init) => {
    assert.equal(
      url,
      'http://nai.test/api/story-bible/facts?novel_id=7&status_filter=active&limit=10',
    )
    assert.equal(init.headers.Authorization, 'Bearer test-token')
    return jsonResponse([])
  }
  try {
    apply(ctx, {
      apiBase: 'http://nai.test/api',
      token: 'test-token',
      timeoutMs: 1000,
    })
    const list = tools.find((tool) => tool.name === 'nai_story_facts_list')
    await list.execute(
      { novel_id: 7, status_filter: 'active', limit: 10 },
      { signal: undefined },
    )
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('更新事实时路径使用 fact_id，请求体不携带该字段', async () => {
  const { ctx, tools } = createHarnessContext()
  const originalFetch = globalThis.fetch
  let captured = null
  globalThis.fetch = async (url, init) => {
    captured = { url, init }
    return jsonResponse({ id: 3, novel_id: 7, status: 'retired' })
  }
  try {
    apply(ctx, { apiBase: 'http://nai.test/api', token: '', timeoutMs: 1000 })
    const update = tools.find((tool) => tool.name === 'nai_story_fact_update')
    await update.execute(
      { fact_id: 3, status: 'retired', value: '云梦泽' },
      { signal: undefined },
    )
    assert.equal(captured.url, 'http://nai.test/api/story-bible/facts/3')
    assert.equal(captured.init.method, 'PUT')
    assert.deepEqual(JSON.parse(captured.init.body), {
      status: 'retired',
      value: '云梦泽',
    })
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('非 2xx 响应转换为包含 detail 的错误', async () => {
  const { ctx, tools } = createHarnessContext()
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () =>
    jsonResponse({ detail: '小说不存在或无权访问' }, 404)
  try {
    apply(ctx, { apiBase: 'http://nai.test/api', token: '', timeoutMs: 1000 })
    const list = tools.find((tool) => tool.name === 'nai_story_facts_list')
    await assert.rejects(
      list.execute({ novel_id: 999 }, { signal: undefined }),
      /小说不存在或无权访问/,
    )
  } finally {
    globalThis.fetch = originalFetch
  }
})
