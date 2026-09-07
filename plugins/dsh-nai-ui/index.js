import Schema from '@deepseek-ai/schemastery'
import { createClient, NaiApiError } from 'dsh-nai'

export const name = 'dsh-nai-ui'
export const inject = ['webServer']

/**
 * 浏览器侧面板通过同源 `/nai-api/*` 读取 Nai 后端，避免在浏览器里保存 JWT。
 * 配置与 dsh-nai 保持一致；通常由 profile 的 cordis.patch.yml 同时覆盖两份。
 */
export const Config = Schema.object({
  apiBase: Schema.string().default('http://127.0.0.1:8000/api'),
  token: Schema.string().default(''),
  timeoutMs: Schema.number().default(60_000),
})

const MAX_PROXY_BODY_BYTES = 10 * 1024 * 1024

function readJsonBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = []
    let size = 0
    req.on('data', (chunk) => {
      size += chunk.length
      if (size > MAX_PROXY_BODY_BYTES) {
        reject(new NaiApiError('请求体超过 10MB 上限', 413))
        chunks.length = 0
        return
      }
      chunks.push(chunk)
    })
    req.on('end', () => {
      if (chunks.length === 0) {
        resolve(undefined)
        return
      }
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')))
      } catch {
        reject(new NaiApiError('请求体不是合法 JSON', 400))
      }
    })
    req.on('error', reject)
  })
}

function sendJson(res, statusCode, payload) {
  res.statusCode = statusCode
  res.setHeader('Content-Type', 'application/json; charset=utf-8')
  res.setHeader('Cache-Control', 'no-store')
  res.end(JSON.stringify(payload))
}

/**
 * Host 侧插件体：把 `/nai-api/*` 代理到 Nai 后端。
 * 该路由由 DSH 自己的 webserver 提供，浏览器始终同源访问，不暴露 CORS 与 token。
 */
export function apply(ctx, config = {}) {
  const client = createClient(config)

  return ctx.webServer.register({
    kind: 'prefix',
    path: '/nai-api',
    handler: async (req, res) => {
      const url = new URL(req.url || '/', 'http://127.0.0.1')
      const path = url.pathname.slice('/nai-api'.length) || '/'
      const method = req.method || 'GET'

      try {
        const body =
          method === 'GET' || method === 'HEAD' || method === 'OPTIONS'
            ? undefined
            : await readJsonBody(req)
        const result = await client.request(path, {
          method,
          params: Object.fromEntries(url.searchParams),
          body,
          includeResponse: true,
        })
        if (result.status === 204 || method === 'HEAD') {
          res.statusCode = result.status
          res.end()
        } else {
          sendJson(res, result.status, result.payload)
        }
      } catch (error) {
        const status = error instanceof NaiApiError ? error.status : 502
        sendJson(res, status, error instanceof NaiApiError && error.payload
          ? error.payload
          : { detail: `Nai 代理请求失败：${error instanceof Error ? error.message : String(error)}` })
      }
    },
  })
}
