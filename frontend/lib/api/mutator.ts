/**
 * Orval 生成客户端的自定义 fetch 传输层。
 *
 * 所有生成端点函数都经 customFetch 发送:统一 token 头、错误信息提取、
 * ApiError 与 Abort 语义,与既有 lib/api.ts 的行为完全一致。
 * OpenAPI 路径已含 /api 前缀,这里只补源站地址。
 */

declare global {
  interface Window {
    /** 桌面壳运行时注入的 API 基址(壳动态分配端口,构建期 env 不可用)。 */
    __NAI_API_BASE__?: string;
  }
}

/**
 * API 基址解析序(壳 P1 件5 运行时覆盖点):
 * 壳注入 window.__NAI_API_BASE__ > 构建期 NEXT_PUBLIC_API_BASE > 本地缺省。
 * 逐请求解析,不支持构建期烧死单一值。
 */
export const resolveApiBase = (): string => {
  if (typeof window !== 'undefined' && window.__NAI_API_BASE__) {
    return window.__NAI_API_BASE__;
  }
  return process.env.NEXT_PUBLIC_API_BASE || 'http://127.0.0.1:8000/api';
};

/** 兼容两类路径:OpenAPI 全路径(/api/...)只补源站,旧相对路径(/novels/...)拼完整 API_BASE。 */
export const resolveApiUrl = (url: string): string => {
  if (url.startsWith('http')) return url;
  const apiBase = resolveApiBase();
  const apiOrigin = apiBase.replace(/\/api\/?$/, '');
  if (url.startsWith('/api/')) return `${apiOrigin}${url}`;
  return `${apiBase}${url}`;
};

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

function isAbortError(error: unknown): boolean {
  return Boolean(
    error &&
      typeof error === 'object' &&
      'name' in error &&
      error.name === 'AbortError',
  );
}

export function extractApiErrorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== 'object') return fallback;

  const record = payload as Record<string, unknown>;
  const detail = record.detail ?? record.message;
  if (typeof detail === 'string' && detail.trim()) return detail;

  if (Array.isArray(detail)) {
    const messages = detail.flatMap((item) => {
      if (typeof item === 'string') return item.trim() ? [item] : [];
      if (!item || typeof item !== 'object') return [];
      const validation = item as Record<string, unknown>;
      if (typeof validation.msg !== 'string') return [];
      const location = Array.isArray(validation.loc)
        ? validation.loc.slice(1).map(String).join('.')
        : '';
      return [`${location ? `${location}：` : ''}${validation.msg}`];
    });
    if (messages.length > 0) return messages.join('；');
  }

  return fallback;
}

export const getHeaders = (): HeadersInit => {
  const token = localStorage.getItem('token');
  return {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
    ...(token && { 'Authorization': `Bearer ${token}` }),
  };
};

const enhancedFetch = async (url: string, options: RequestInit = {}): Promise<Response> => {
  const fullUrl = resolveApiUrl(url);

  try {
    return await fetch(fullUrl, {
      ...options,
      headers: {
        ...getHeaders(),
        ...options.headers,
      },
    });
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }

    console.error('网络请求失败：', error);

    if (error instanceof TypeError && error.message.includes('fetch')) {
      // 真断连与 500 未带 CORS 头被浏览器吞成 Failed to fetch 都会走到这里，
      // 无法区分，统一给作者语言；自建服务的深度排查走登录页调试面板。
      throw new Error('暂时连不上服务器，请稍后再试');
    }

    throw error;
  }
};

const handleApiResponse = async <T>(response: Response): Promise<T> => {
  if (!response.ok) {
    let errorMessage = `请求失败 (${response.status})`;

    try {
      const errorData: unknown = await response.json();
      errorMessage = extractApiErrorMessage(errorData, errorMessage);
    } catch {
      if (response.status === 404) {
        errorMessage = 'API端点不存在';
      } else if (response.status === 500) {
        errorMessage = '服务器内部错误';
      } else if (response.status === 0) {
        errorMessage = '网络连接失败，请检查CORS设置';
      }
    }

    // 5xx 一律按状态码分流给作者语言：服务端 detail/堆栈是工程语言，不透传。
    if (response.status >= 500) {
      errorMessage = response.status >= 502
        ? '服务器暂时不可用，请稍后再试'
        : '服务器开小差了，请稍后再试';
    }

    throw new ApiError(errorMessage, response.status);
  }

  if (response.status === 204) return undefined as T;
  return response.json();
};

export { enhancedFetch, handleApiResponse };

/** Orval fetch client 的 mutator 入口;兼容直接传 API_BASE 相对路径的旧调用。 */
export async function customFetch<T>(url: string, options: RequestInit = {}): Promise<T> {
  return handleApiResponse<T>(await enhancedFetch(url, options));
}
