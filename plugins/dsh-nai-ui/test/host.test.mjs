import test from 'node:test'
import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import { apply } from '../index.js'

function createHarnessContext() {
  const routes = []
  return {
    routes,
    ctx: {
      webServer: {
        register(route) {
          routes.push(route)
          return () => {}
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

function createResponse() {
  const headers = {}
  const response = {
    statusCode: 200,
    headers,
    chunks: [],
    setHeader(name, value) {
      headers[name] = value
    },
    end(chunk) {
      if (chunk) {
        response.chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk))
      }
      response.body = Buffer.concat(response.chunks).toString('utf8')
    },
  }
  return response
}

function getRequest(url) {
  return { url, method: 'GET', on() {}, destroy() {} }
}

function postRequest(url, payload) {
  const req = new EventEmitter()
  req.url = url
  req.method = 'POST'
  req.destroy = () => {}
  process.nextTick(() => {
    req.emit('data', Buffer.from(JSON.stringify(payload)))
    req.emit('end')
  })
  return req
}

test('注册 /nai-api 前缀路由', () => {
  const { ctx, routes } = createHarnessContext()
  apply(ctx, { apiBase: 'http://nai.test/api', token: '', timeoutMs: 1000 })

  assert.equal(routes.length, 1)
  assert.equal(routes[0].kind, 'prefix')
  assert.equal(routes[0].path, '/nai-api')
})

test('健康检查代理到 Nai 后端并返回 JSON', async () => {
  const { ctx, routes } = createHarnessContext()
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (url, init) => {
    assert.equal(url, 'http://nai.test/api/health')
    assert.equal(init.headers.Authorization, 'Bearer test-token')
    return jsonResponse({ status: 'healthy', app_name: 'Nai', version: '0.1.0' })
  }
  try {
    apply(ctx, { apiBase: 'http://nai.test/api', token: 'test-token', timeoutMs: 1000 })
    const response = createResponse()
    await routes[0].handler(getRequest('/nai-api/health'), response)
    assert.equal(response.statusCode, 200)
    assert.deepEqual(JSON.parse(response.body), {
      status: 'healthy',
      app_name: 'Nai',
      version: '0.1.0',
    })
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('查询参数透传并去掉 /nai-api 前缀', async () => {
  const { ctx, routes } = createHarnessContext()
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (url) => {
    assert.equal(
      url,
      'http://nai.test/api/story-bible/facts?novel_id=7&limit=10',
    )
    return jsonResponse([])
  }
  try {
    apply(ctx, { apiBase: 'http://nai.test/api', token: '', timeoutMs: 1000 })
    const response = createResponse()
    await routes[0].handler(
      getRequest('/nai-api/story-bible/facts?novel_id=7&limit=10'),
      response,
    )
    assert.equal(response.statusCode, 200)
    assert.deepEqual(JSON.parse(response.body), [])
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('POST 请求体解析后透传', async () => {
  const { ctx, routes } = createHarnessContext()
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (url, init) => {
    assert.equal(url, 'http://nai.test/api/story-bible/facts')
    assert.equal(init.method, 'POST')
    assert.deepEqual(JSON.parse(init.body), {
      novel_id: 7,
      subject: '林渡',
      attribute: '身份',
      value: '邮差',
    })
    return jsonResponse({ id: 1 })
  }
  try {
    apply(ctx, { apiBase: 'http://nai.test/api', token: '', timeoutMs: 1000 })
    const response = createResponse()
    await routes[0].handler(
      postRequest('/nai-api/story-bible/facts', {
        novel_id: 7,
        subject: '林渡',
        attribute: '身份',
        value: '邮差',
      }),
      response,
    )
    assert.equal(response.statusCode, 200)
    assert.equal(JSON.parse(response.body).id, 1)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('后端错误转换为 502 与 detail', async () => {
  const { ctx, routes } = createHarnessContext()
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => {
    throw new Error('小说不存在或无权访问')
  }
  try {
    apply(ctx, { apiBase: 'http://nai.test/api', token: '', timeoutMs: 1000 })
    const response = createResponse()
    await routes[0].handler(getRequest('/nai-api/novels/999'), response)
    assert.equal(response.statusCode, 502)
    assert.match(JSON.parse(response.body).detail, /小说不存在或无权访问/)
  } finally {
    globalThis.fetch = originalFetch
  }
})

for (const status of [401, 404, 409, 422]) {
  test(`代理保留后端 ${status} 状态和冲突信息`, async () => {
    const { ctx, routes } = createHarnessContext()
    const originalFetch = globalThis.fetch
    const payload = { detail: '需要处理业务错误', current_version: 4 }
    globalThis.fetch = async () => jsonResponse(payload, status)
    try {
      apply(ctx, { apiBase: 'http://nai.test/api' })
      const response = createResponse()
      await routes[0].handler(getRequest('/nai-api/novels/7/chapters/9'), response)
      assert.equal(response.statusCode, status)
      assert.deepEqual(JSON.parse(response.body), payload)
    } finally {
      globalThis.fetch = originalFetch
    }
  })
}

test('代理保留创建成功的 201 状态', async () => {
  const { ctx, routes } = createHarnessContext()
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => jsonResponse({ id: 1 }, 201)
  try {
    apply(ctx, { apiBase: 'http://nai.test/api' })
    const response = createResponse()
    await routes[0].handler(postRequest('/nai-api/novels', { title: '新书' }), response)
    assert.equal(response.statusCode, 201)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('代理不会把无效请求 JSON 转发到后端', async () => {
  const { ctx, routes } = createHarnessContext()
  const originalFetch = globalThis.fetch
  let called = false
  globalThis.fetch = async () => { called = true; return jsonResponse({}) }
  try {
    apply(ctx, { apiBase: 'http://nai.test/api' })
    const req = new EventEmitter()
    Object.assign(req, { url: '/nai-api/novels', method: 'POST' })
    process.nextTick(() => { req.emit('data', Buffer.from('{')); req.emit('end') })
    const response = createResponse()
    await routes[0].handler(req, response)
    assert.equal(response.statusCode, 400)
    assert.equal(called, false)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('超限请求返回 413，保留连接以便发送错误响应', async () => {
  const { ctx, routes } = createHarnessContext()
  const req = new EventEmitter()
  let destroyed = false
  Object.assign(req, { url: '/nai-api/novels', method: 'POST', destroy() { destroyed = true } })
  process.nextTick(() => {
    req.emit('data', Buffer.alloc(10 * 1024 * 1024 + 1))
    req.emit('end')
  })
  apply(ctx, { apiBase: 'http://nai.test/api' })
  const response = createResponse()
  await routes[0].handler(req, response)
  assert.equal(response.statusCode, 413)
  assert.equal(destroyed, false)
})
