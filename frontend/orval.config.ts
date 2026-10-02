import { defineConfig } from 'orval';

// 契约唯一事实源是后端导出的 openapi.json;生成物在 lib/api/generated/,
// 不手工维护。SSE 不在 OpenAPI 范畴,流式客户端保留在 lib/sse.ts。
export default defineConfig({
  moshu: {
    input: './openapi.json',
    output: {
      target: './lib/api/generated/client.ts',
      schemas: './lib/api/generated/model',
      client: 'fetch',
      mock: false,
      clean: true,
      mode: 'split',
      override: {
        mutator: {
          path: './lib/api/mutator.ts',
          name: 'customFetch',
        },
        query: { useQuery: false, useMutation: false },
      },
    },
  },
});
