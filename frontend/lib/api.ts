import type {
  LoginRequest,
  RegisterRequest,
  AuthResponse,
  User,
  Novel,
  NovelCreate,
  NovelStatistics,
  NovelStatisticsResponse,
  Chapter,
  ChapterCreate,
  ChapterNextCreate,
  ChapterSummary,
  ChapterSummaryPage,
  ChapterUpdate,
  GenerationFinalConsistency,
  GenerationMetadata,
  StyleSample,
  AgentWorkflowTrace,
} from '@/types';
import { readSSEFromResponse, SSEEvent } from '@/lib/sse';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://127.0.0.1:8000/api';

interface RequestOptions {
  signal?: AbortSignal;
}

function isAbortError(error: unknown): boolean {
  return Boolean(
    error &&
    typeof error === 'object' &&
    'name' in error &&
    error.name === 'AbortError',
  );
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

function extractApiErrorMessage(payload: unknown, fallback: string): string {
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

/**
 * 获取请求头（包含认证Token）
 */
const getHeaders = (): HeadersInit => {
  const token = localStorage.getItem('token');
  return {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
    ...(token && { 'Authorization': `Bearer ${token}` }),
  };
};

/**
 * 增强的 fetch 函数，统一处理地址、认证和网络错误。
 */
const enhancedFetch = async (url: string, options: RequestInit = {}): Promise<Response> => {
  const fullUrl = url.startsWith('http') ? url : `${API_BASE}${url}`;

  try {
    const response = await fetch(fullUrl, {
      ...options,
      headers: {
        ...getHeaders(),
        ...options.headers,
      },
    });

    return response;
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }

    console.error('网络请求失败：', error);
    
    if (error instanceof TypeError && error.message.includes('fetch')) {
      throw new Error(`无法连接到服务器 (${fullUrl})。请检查：\n1. 服务器是否运行\n2. 网络连接是否正常\n3. 防火墙设置`);
    }
    
    throw error;
  }
};

/**
 * 处理API响应的通用函数
 */
const handleApiResponse = async <T>(response: Response): Promise<T> => {
  if (!response.ok) {
    let errorMessage = `请求失败 (${response.status})`;
    
    try {
      const errorData: unknown = await response.json();
      errorMessage = extractApiErrorMessage(errorData, errorMessage);
    } catch {
      // 如果无法解析JSON，使用默认错误消息
      if (response.status === 404) {
        errorMessage = 'API端点不存在';
      } else if (response.status === 500) {
        errorMessage = '服务器内部错误';
      } else if (response.status === 0) {
        errorMessage = '网络连接失败，请检查CORS设置';
      }
    }
    
    throw new ApiError(errorMessage, response.status);
  }
  
  return response.json();
};

/**
 * API客户端
 */
export const api = {
  // ==================== 认证相关 ====================

  /**
   * 用户登录
   */
  async login(data: LoginRequest): Promise<AuthResponse> {
    const response = await enhancedFetch('/auth/login', {
      method: 'POST',
      body: JSON.stringify(data),
    });
    return handleApiResponse<AuthResponse>(response);
  },

  /**
   * 用户注册
   */
  async register(data: RegisterRequest): Promise<AuthResponse> {
    const response = await enhancedFetch('/auth/register', {
      method: 'POST',
      body: JSON.stringify(data),
    });
    return handleApiResponse<AuthResponse>(response);
  },

  /**
   * 获取当前用户信息
   */
  async getCurrentUser(): Promise<User> {
    const response = await enhancedFetch('/auth/me');
    return handleApiResponse<User>(response);
  },

  // ==================== 小说管理 ====================

  /**
   * 获取用户的所有小说
   */
  async getNovels(): Promise<Novel[]> {
    const res = await fetch(`${API_BASE}/novels/`, {
      headers: getHeaders(),
    });
    if (!res.ok) {
      let errorMessage = '获取小说列表失败';
      try {
        const error = await res.json();
        errorMessage = extractApiErrorMessage(error, errorMessage);
      } catch {
        // 非 JSON 响应保留统一错误信息，同时保留状态码供调用方判断。
      }
      throw new ApiError(errorMessage, res.status);
    }
    return res.json();
  },

  /**
   * 一次获取当前用户全部小说的章节数和总字数，避免仪表盘逐本扫描章节。
   */
  async getNovelStatistics(
    options: RequestOptions = {},
  ): Promise<NovelStatistics[]> {
    const res = await enhancedFetch('/novels/statistics', {
      signal: options.signal,
    });
    const payload = await handleApiResponse<
      NovelStatisticsResponse | NovelStatistics[]
    >(res);
    return Array.isArray(payload) ? payload : payload.items;
  },

  /**
   * 获取单个小说详情
   */
  async getNovel(id: number, options: RequestOptions = {}): Promise<Novel> {
    const res = await enhancedFetch(`/novels/${id}`, {
      signal: options.signal,
    });
    return handleApiResponse<Novel>(res);
  },

  /**
   * 创建小说
   */
  async createNovel(data: NovelCreate): Promise<Novel> {
    const res = await fetch(`${API_BASE}/novels/`, {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(extractApiErrorMessage(error, '创建小说失败'));
    }
    return res.json();
  },

  /**
   * 更新小说
   */
  async updateNovel(id: number, data: Partial<NovelCreate>): Promise<Novel> {
    const res = await fetch(`${API_BASE}/novels/${id}`, {
      method: 'PUT',
      headers: getHeaders(),
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(extractApiErrorMessage(error, '更新小说失败'));
    }
    return res.json();
  },

  /**
   * 删除小说
   */
  async deleteNovel(id: number): Promise<void> {
    const res = await fetch(`${API_BASE}/novels/${id}`, {
      method: 'DELETE',
      headers: getHeaders(),
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(extractApiErrorMessage(error, '删除小说失败'));
    }
  },

  // ==================== 章节管理 ====================

  /**
   * 获取小说的全部章节摘要，不下载正文。
   */
  async getAllChapterSummaries(
    novelId: number,
    options: RequestOptions = {},
  ): Promise<ChapterSummary[]> {
    const summaries: ChapterSummary[] = [];
    let page = 1;
    let hasMore = true;

    while (hasMore) {
      const result = await api.getChapterSummaries(
        novelId,
        { page, pageSize: 100 },
        options,
      );
      const knownIds = new Set(summaries.map((chapter) => chapter.id));
      const newItems = result.items.filter((chapter) => !knownIds.has(chapter.id));
      summaries.push(...newItems);
      hasMore = result.has_more && newItems.length > 0;
      page += 1;
    }

    return summaries;
  },

  /**
   * 兼容旧页面的完整章节加载。新页面应使用摘要分页和单章详情接口。
   */
  async getChapters(novelId: number, options: RequestOptions = {}): Promise<Chapter[]> {
    const summaries = await api.getAllChapterSummaries(novelId, options);

    if (summaries.every((chapter) => typeof (chapter as Chapter).content === 'string')) {
      return summaries as Chapter[];
    }

    const chapters = new Array<Chapter>(summaries.length);
    let cursor = 0;
    const workers = Array.from(
      { length: Math.min(6, summaries.length) },
      async () => {
        while (cursor < summaries.length) {
          const index = cursor;
          cursor += 1;
          chapters[index] = await api.getChapter(
            novelId,
            summaries[index].id,
            options,
          );
        }
      },
    );
    await Promise.all(workers);
    return chapters;
  },

  /**
   * 分页获取章节摘要。兼容服务端迁移期间返回纯数组的情况。
   */
  async getChapterSummaries(
    novelId: number,
    params: { page?: number; pageSize?: number } = {},
    options: RequestOptions = {},
  ): Promise<ChapterSummaryPage> {
    const page = Math.max(1, params.page ?? 1);
    const pageSize = Math.min(100, Math.max(1, params.pageSize ?? 50));
    const query = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
    });
    const res = await enhancedFetch(
      `/novels/${novelId}/chapters?${query.toString()}`,
      { signal: options.signal },
    );
    const payload = await handleApiResponse<ChapterSummaryPage | ChapterSummary[]>(res);

    if (Array.isArray(payload)) {
      return {
        items: payload,
        total: (page - 1) * pageSize + payload.length,
        page,
        page_size: pageSize,
        has_more: payload.length === pageSize,
      };
    }

    return {
      items: payload.items ?? [],
      total:
        payload.total ??
        (page - 1) * pageSize + (payload.items?.length ?? 0),
      page: payload.page ?? page,
      page_size: payload.page_size ?? pageSize,
      has_more:
        payload.has_more ??
        page * pageSize < (payload.total ?? 0),
    };
  },

  /**
   * 获取单个章节详情
   */
  async getChapter(
    novelId: number,
    chapterId: number,
    options: RequestOptions = {},
  ): Promise<Chapter> {
    const res = await enhancedFetch(`/novels/${novelId}/chapters/${chapterId}`, {
      signal: options.signal,
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(extractApiErrorMessage(error, '获取章节详情失败'));
    }
    return res.json();
  },

  /**
   * 创建章节
   */
  async createChapter(novelId: number, data: ChapterCreate): Promise<Chapter> {
    const res = await fetch(`${API_BASE}/novels/${novelId}/chapters`, {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(extractApiErrorMessage(error, '创建章节失败'));
    }
    return res.json();
  },

  /**
   * 创建下一章，章节号由服务端在事务中分配。
   */
  async createNextChapter(
    novelId: number,
    data: ChapterNextCreate = {},
    options: RequestOptions = {},
  ): Promise<Chapter> {
    const res = await enhancedFetch(`/novels/${novelId}/chapters/next`, {
      method: 'POST',
      signal: options.signal,
      body: JSON.stringify(data),
    });
    return handleApiResponse<Chapter>(res);
  },

  /**
   * 更新章节
   */
  async updateChapter(
    novelId: number,
    chapterId: number,
    data: ChapterUpdate,
    options: RequestOptions = {},
  ): Promise<Chapter> {
    const res = await enhancedFetch(`/novels/${novelId}/chapters/${chapterId}`, {
      method: 'PUT',
      signal: options.signal,
      body: JSON.stringify(data),
    });
    return handleApiResponse<Chapter>(res);
  },

  /**
   * 删除章节
   */
  async deleteChapter(novelId: number, chapterId: number): Promise<void> {
    const res = await fetch(`${API_BASE}/novels/${novelId}/chapters/${chapterId}`, {
      method: 'DELETE',
      headers: getHeaders(),
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(extractApiErrorMessage(error, '删除章节失败'));
    }
  },

  // ==================== AI生成相关 ====================

  /**
   * 章节续写（非流式）
   */
  async continueChapter(data: {
    novel_id: number;
    chapter_id: number;
    current_content: string;
    target_length?: number;
    style_strength?: number;
    pace?: string;
    tone?: string;
    use_rag_style?: boolean;
    style_sample_id?: number | null;
    plot_direction_hint?: string;
  }): Promise<{
    content: string;
    length: number;
    style_features?: string[];
    style_sample_id?: number | null;
    rag_style_context?: string[];
    rag_story_context?: string[];
    agent_outputs?: {
      agent_type: string;
      content: string;
      metadata?: Record<string, any>;
    }[];
    workflow_trace?: AgentWorkflowTrace | null;
    consistency_checks?: unknown[];
    retry_count?: number;
    final_consistency?: GenerationFinalConsistency;
    settings?: {
      pace: string;
      tone: string;
      style_strength: number;
    };
  }> {
    const res = await fetch(`${API_BASE}/generation/continue`, {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(extractApiErrorMessage(error, 'AI续写失败'));
    }
    return res.json();
  },

  /**
   * 章节续写（流式，SSE）
   * @param data 续写参数
   * @param onChunk 接收到每个文本块时的回调
   * @param onMetadata 接收到元数据时的回调
   * @param onDone 完成时的回调
   * @param onError 错误时的回调
   */
  async continueChapterStream(
    data: {
      novel_id: number;
      chapter_id: number;
      current_content: string;
      target_length?: number;
      style_strength?: number;
      pace?: string;
      tone?: string;
      use_rag_style?: boolean;
      style_sample_id?: number | null;
      plot_direction_hint?: string;
    },
    callbacks: {
      onChunk: (chunk: string) => void;
      onMetadata?: (metadata: GenerationMetadata) => void;
      onDone?: () => void;
      onEvent?: (event: SSEEvent) => void;
      onError?: (error: Error) => void;
    },
    options: RequestOptions = {},
  ): Promise<void> {
    try {
      const res = await fetch(`${API_BASE}/generation/continue-stream`, {
        method: 'POST',
        headers: getHeaders(),
        signal: options.signal,
        body: JSON.stringify(data),
      });

      if (!res.ok) {
        const error = await res.json();
        throw new Error(extractApiErrorMessage(error, 'AI续写失败'));
      }

      await readSSEFromResponse(
        res,
        {
          onEvent: (event) => {
            callbacks.onEvent?.(event);
          },
          onChunk: (chunk) => {
            callbacks.onChunk(chunk);
          },
          onMetadata: (metadata) => {
            if (metadata && typeof metadata === 'object') {
              callbacks.onMetadata?.(metadata as GenerationMetadata);
            }
          },
          onDone: () => {
            callbacks.onDone?.();
          },
        },
        { signal: options.signal },
      );
    } catch (error) {
      callbacks.onError?.(error instanceof Error ? error : new Error('Unknown error'));
      throw error;
    }
  },

  /**
   * 获取文风样本列表
   */
  async getStyleSamples(novelId: number): Promise<StyleSample[]> {
    const res = await fetch(`${API_BASE}/style/samples?novel_id=${novelId}`, {
      headers: getHeaders(),
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(extractApiErrorMessage(error, '获取文风样本失败'));
    }
    return res.json();
  },

  /**
   * 创建文风样本
   */
  async createStyleSample(data: {
    novel_id: number;
    name: string;
    sample_text: string;
  }): Promise<StyleSample> {
    const res = await fetch(`${API_BASE}/style/samples`, {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(extractApiErrorMessage(error, '创建文风样本失败'));
    }
    return res.json();
  },

  /**
   * 生成小说大纲
   */
  async generateOutline(data: {
    novel_id: number;
    theme: string;
    target_chapters?: number;
  }): Promise<{ outline: string; chapters: number }> {
    const res = await fetch(`${API_BASE}/generation/outline`, {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(extractApiErrorMessage(error, '大纲生成失败'));
    }
    return res.json();
  },

  /**
   * 生成角色设定
   */
  async generateCharacter(data: {
    novel_id: number;
    character_type: string;
    character_description: string;
  }): Promise<{ character: string; type: string }> {
    const res = await fetch(`${API_BASE}/generation/character`, {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(extractApiErrorMessage(error, '角色生成失败'));
    }
    return res.json();
  },

  /**
   * AI 初始化小说设定
   */
  async initNovel(data: {
    novel_id: number;
    target_chapters?: number;
    theme?: string;
  }): Promise<{
    novel_id: number;
    worldview: string;
    main_characters: string[];
    outline: string;
    plot_hooks: string[];
  }> {
    const res = await fetch(`${API_BASE}/generation/init`, {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(extractApiErrorMessage(error, '初始化设定失败'));
    }
    return res.json();
  },

  /**
   * 生成剧情走向选项
   */
  async getPlotOptions(data: {
    novel_id: number;
    chapter_id: number;
    current_content: string;
    num_options?: number;
  }): Promise<{
    novel_id: number;
    chapter_id: number;
    options: {
      id: number;
      title: string;
      summary: string;
      impact?: string | null;
      risk?: string | null;
    }[];
  }> {
    const res = await fetch(`${API_BASE}/generation/plot-options`, {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(extractApiErrorMessage(error, '生成剧情选项失败'));
    }
    return res.json();
  },

  /**
   * AI 自动生成并创建新章节
   */
  async autoCreateChapter(data: {
    novel_id: number;
    base_chapter_id?: number;
    target_length?: number;
    theme?: string;
  }): Promise<Chapter> {
    const res = await fetch(`${API_BASE}/generation/auto-chapter`, {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(extractApiErrorMessage(error, 'AI自动生成章节失败'));
    }
    return res.json();
  },

  /**
   * 局部文本改写
   */
  async rewriteText(data: {
    novel_id: number;
    chapter_id?: number;
    original_text: string;
    rewrite_type?: 'polish' | 'rewrite' | 'shorten' | 'extend';
    style_hint?: string;
    target_length?: number;
  }): Promise<{ rewritten_text: string }> {
    const res = await fetch(`${API_BASE}/generation/rewrite`, {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(extractApiErrorMessage(error, 'AI改写失败'));
    }
    return res.json();
  },

  /**
   * 一致性检查（流式）
   */
  async checkConsistencyStream(
    data: {
      novel_id: number;
      chapter: number;
      content: string;
      current_day?: number;
    },
    callbacks: {
      onEvent?: (event: SSEEvent) => void;
      onSummary?: (summary: any) => void;
      onError?: (error: Error) => void;
    }
  ): Promise<void> {
    try {
      const res = await fetch(`${API_BASE}/consistency/check-stream`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify(data),
      });

      if (!res.ok) {
        const error = await res.json();
        throw new Error(extractApiErrorMessage(error, '一致性检查失败'));
      }

      await readSSEFromResponse(res, {
        onEvent: (event) => {
          callbacks.onEvent?.(event);
          if ((event as any).type === 'summary') {
            callbacks.onSummary?.(event);
          }
        },
      });
    } catch (error) {
      callbacks.onError?.(error instanceof Error ? error : new Error('Unknown error'));
      throw error;
    }
  },

  /**
   * 资料检索（用于历史/现实背景等查询）
   */
  async researchSearch(data: {
    query: string;
    novel_id?: number;
    category?: string;
  }): Promise<{
    query: string;
    results: {
      title: string;
      summary: string;
      source: string;
      url?: string | null;
      metadata?: Record<string, any>;
    }[];
  }> {
    const res = await fetch(`${API_BASE}/research/search`, {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(extractApiErrorMessage(error, '资料检索失败'));
    }
    return res.json();
  },
};
