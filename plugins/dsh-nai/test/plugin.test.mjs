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
      'nai_novels_list',
      'nai_novel_create',
      'nai_novel_get',
      'nai_characters_list',
      'nai_story_facts_list',
      'nai_story_events_list',
      'nai_story_fact_create',
      'nai_story_fact_update',
      'nai_story_event_create',
      'nai_chapters_list',
      'nai_chapter_get',
      'nai_chapter_create_next',
      'nai_chapter_update',
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

test('小说列表与详情使用正确的路径和查询参数', async () => {
  const { ctx, tools } = createHarnessContext()
  const calls = []
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init })
    return jsonResponse([])
  }
  try {
    apply(ctx, { apiBase: 'http://nai.test/api', token: '', timeoutMs: 1000 })
    await tools
      .find((tool) => tool.name === 'nai_novels_list')
      .execute({ skip: 0, limit: 10 }, { signal: undefined })
    await tools
      .find((tool) => tool.name === 'nai_novel_get')
      .execute({ novel_id: 7 }, { signal: undefined })
  } finally {
    globalThis.fetch = originalFetch
  }

  assert.equal(calls[0].url, 'http://nai.test/api/novels?skip=0&limit=10')
  assert.equal(calls[0].init.method, 'GET')
  assert.equal(calls[1].url, 'http://nai.test/api/novels/7')
})

test('创建小说时 POST 到 /novels', async () => {
  const { ctx, tools } = createHarnessContext()
  let captured = null
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (url, init) => {
    captured = { url, init }
    return jsonResponse({ id: 7, title: '雾港来信' })
  }
  try {
    apply(ctx, { apiBase: 'http://nai.test/api', token: '', timeoutMs: 1000 })
    await tools
      .find((tool) => tool.name === 'nai_novel_create')
      .execute(
        { title: '雾港来信', genre: '悬疑奇幻', description: '简介' },
        { signal: undefined },
      )
  } finally {
    globalThis.fetch = originalFetch
  }

  assert.equal(captured.url, 'http://nai.test/api/novels')
  assert.equal(captured.init.method, 'POST')
  assert.deepEqual(JSON.parse(captured.init.body), {
    title: '雾港来信',
    genre: '悬疑奇幻',
    description: '简介',
  })
})

test('角色列表路径携带 novel_id，其余参数进入查询串', async () => {
  const { ctx, tools } = createHarnessContext()
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (url) => {
    assert.equal(
      url,
      'http://nai.test/api/characters/novel/7?skip=0&importance_level=main',
    )
    return jsonResponse([])
  }
  try {
    apply(ctx, { apiBase: 'http://nai.test/api', token: '', timeoutMs: 1000 })
    await tools
      .find((tool) => tool.name === 'nai_characters_list')
      .execute(
        { novel_id: 7, skip: 0, importance_level: 'main' },
        { signal: undefined },
      )
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('章节详情路径包含 novel_id 与 chapter_id', async () => {
  const { ctx, tools } = createHarnessContext()
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (url) => {
    assert.equal(url, 'http://nai.test/api/novels/7/chapters/9')
    return jsonResponse({ id: 9, novel_id: 7, version: 3, content: '正文' })
  }
  try {
    apply(ctx, { apiBase: 'http://nai.test/api', token: '', timeoutMs: 1000 })
    const value = await tools
      .find((tool) => tool.name === 'nai_chapter_get')
      .execute({ novel_id: 7, chapter_id: 9 }, { signal: undefined })
    assert.equal(value.version, 3)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('创建下一章时请求体不携带 novel_id', async () => {
  const { ctx, tools } = createHarnessContext()
  let captured = null
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (url, init) => {
    captured = { url, init }
    return jsonResponse({ id: 9, novel_id: 7, chapter_number: 3 })
  }
  try {
    apply(ctx, { apiBase: 'http://nai.test/api', token: '', timeoutMs: 1000 })
    await tools
      .find((tool) => tool.name === 'nai_chapter_create_next')
      .execute(
        { novel_id: 7, title: '第三章', content: '正文' },
        { signal: undefined },
      )
  } finally {
    globalThis.fetch = originalFetch
  }

  assert.equal(captured.url, 'http://nai.test/api/novels/7/chapters/next')
  assert.equal(captured.init.method, 'POST')
  assert.deepEqual(JSON.parse(captured.init.body), {
    title: '第三章',
    content: '正文',
  })
})

test('更新章节时携带 expected_version，路径参数不进入请求体', async () => {
  const { ctx, tools } = createHarnessContext()
  let captured = null
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (url, init) => {
    captured = { url, init }
    return jsonResponse({ id: 9, novel_id: 7, version: 4 })
  }
  try {
    apply(ctx, { apiBase: 'http://nai.test/api', token: '', timeoutMs: 1000 })
    await tools
      .find((tool) => tool.name === 'nai_chapter_update')
      .execute(
        { novel_id: 7, chapter_id: 9, expected_version: 3,
          expected_novel_lifecycle_id: 'a'.repeat(32),
          expected_chapter_lifecycle_id: 'b'.repeat(32),
          title: '第三章', content: '新正文' },
        { signal: undefined },
      )
  } finally {
    globalThis.fetch = originalFetch
  }

  assert.equal(captured.url, 'http://nai.test/api/novels/7/chapters/9')
  assert.equal(captured.init.method, 'PUT')
  assert.deepEqual(JSON.parse(captured.init.body), {
    expected_version: 3,
    expected_novel_lifecycle_id: 'a'.repeat(32),
    expected_chapter_lifecycle_id: 'b'.repeat(32),
    title: '第三章',
    content: '新正文',
  })
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

test('422 校验错误会展开 detail 数组中的字段信息', async () => {
  const { ctx, tools } = createHarnessContext()
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () =>
    jsonResponse(
      {
        detail: [
          { loc: ['body', 'expected_version'], msg: 'Field required', type: 'missing' },
        ],
      },
      422,
    )
  try {
    apply(ctx, { apiBase: 'http://nai.test/api', token: '', timeoutMs: 1000 })
    const update = tools.find((tool) => tool.name === 'nai_chapter_update')
    await assert.rejects(
      update.execute(
        { novel_id: 7, chapter_id: 9, expected_version: 3,
          expected_novel_lifecycle_id: 'a'.repeat(32),
          expected_chapter_lifecycle_id: 'b'.repeat(32) },
        { signal: undefined },
      ),
      /body\.expected_version: Field required/,
    )
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
