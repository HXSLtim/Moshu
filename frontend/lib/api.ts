import type { WritingTurn, WritingTurnCreate } from '@/types/writingChat';
import { generationJobsApi, isGenerationPending, type GenerationJob } from '@/lib/generationJobs';
import type {
  LoginRequest,
  RegisterRequest,
  AuthResponse,
  User,
  Novel,
  NovelCreate,
  IdeaParseResult,
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
import type { StoryFact, StoryFactCreate, StoryFactUpdate, StoryEvent, StoryEventCreate, StoryEventUpdate } from '@/types/storyBible';

interface RequestOptions {
  signal?: AbortSignal;
}

import {
  ApiError,
  customFetch,
  enhancedFetch,
  extractApiErrorMessage,
  getHeaders,
  handleApiResponse,
} from './api/mutator';

export { ApiError, extractApiErrorMessage } from './api/mutator';

/** 统一请求入口:与生成客户端共用同一传输层(鉴权、错误提取、Abort)。 */
export async function apiRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  return customFetch<T>(path, options);
}

function jobTurn(job: GenerationJob<WritingTurn>, fallback?: WritingTurnCreate): WritingTurn {
  if (job.result) return { ...job.result, job_id: job.id, job_status: job.status };
  return { id: 0, job_id: job.id, job_status: job.status, request_id: job.request_id,
    novel_id: job.novel_id, novel_lifecycle_id: job.novel_lifecycle_id,
    chapter_id: job.chapter_id ?? fallback?.chapter_id ?? 0, chapter_title: job.chapter_title ?? '已保存的创作任务',
    mode: (job.mode as WritingTurn['mode']) ?? fallback?.mode ?? 'discuss', user_text: job.message ?? fallback?.message ?? '已保存的创作请求',
    assistant_text: '', base_content_hash: '', status: job.status === 'queued' || job.status === 'running' ? 'pending' : job.status === 'completed' ? 'failed' : job.status,
    error: job.error ?? (job.status === 'completed' ? '任务未返回有效对话，请重新发送' : job.status === 'cancelled' ? '已停止生成' : null), created_at: job.created_at };
}

function pauseForGeneration(signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const abort = () => { clearTimeout(timer); signal?.removeEventListener('abort', abort); reject(new DOMException('已停止等待', 'AbortError')); };
    const timer = setTimeout(() => { signal?.removeEventListener('abort', abort); resolve(); }, 1000);
    if (signal?.aborted) abort(); else signal?.addEventListener('abort', abort, { once: true });
  });
}

export const api = {
  async listWritingTurns(novelId: number, before?: number, options: RequestOptions = {}): Promise<WritingTurn[]> {
    const turns: WritingTurn[] = await handleApiResponse(await enhancedFetch(`/writing-chat/${novelId}/turns?limit=30${before ? `&before=${before}` : ''}`, options));
    if (before) return turns;
    const jobs = await generationJobsApi.list<WritingTurn>(novelId, 'chat', options.signal);
    const entries = new Map(turns.map((turn) => [turn.request_id, turn]));
    for (const job of jobs) {
      const turn = entries.get(job.request_id);
      entries.set(job.request_id, turn ? { ...turn, job_id: job.id, job_status: job.status } : jobTurn(job));
    }
    return [...entries.values()].sort((a, b) => a.created_at.localeCompare(b.created_at));
  },
  async sendWritingTurn(novelId: number, data: WritingTurnCreate, options: RequestOptions = {}): Promise<WritingTurn> {
    if (!data.expected_novel_lifecycle_id) throw new Error('请先完成作品身份核验再发送');
    let job = await generationJobsApi.create<WritingTurn>({ request_id: data.request_id, kind: 'chat', novel_id: novelId, expected_novel_lifecycle_id: data.expected_novel_lifecycle_id, payload: data }, options.signal);
    while (isGenerationPending(job)) {
      await pauseForGeneration(options.signal);
      job = await generationJobsApi.get<WritingTurn>(novelId, job.id, options.signal);
    }
    return jobTurn(job, data);
  },
  /**
   * 创作对话的流式入口：文本边生成边回调，工具提案单独成事件。
   * 只有收到 done 才算完成；中途 EOF 会抛出错误，不会伪装成功。
   */
  async streamWritingTurn(
    novelId: number,
    data: WritingTurnCreate,
    callbacks: {
      onTurn?: (turn: Partial<WritingTurn>) => void;
      onChunk?: (content: string) => void;
      onTool?: (name: string, payload: Record<string, unknown>) => void;
      onDone?: (turn: WritingTurn) => void;
    },
    options: RequestOptions = {},
  ): Promise<void> {
    const res = await enhancedFetch(`/writing-chat/${novelId}/turns/stream`, {
      method: 'POST',
      body: JSON.stringify(data),
      signal: options.signal,
    });
    if (!res.ok) {
      let message = `请求失败 (${res.status})`;
      try { message = extractApiErrorMessage(await res.json(), message); } catch { /* 保持默认信息 */ }
      throw new ApiError(message, res.status);
    }
    await readSSEFromResponse(res, {
      onEvent: (event) => {
        if (event.type === 'metadata') {
          callbacks.onTurn?.((event.data as { turn?: Partial<WritingTurn> } | undefined)?.turn ?? {});
        } else if (event.type === 'chunk') {
          callbacks.onChunk?.(typeof event.content === 'string' ? event.content : '');
        } else if (event.type === 'tool') {
          callbacks.onTool?.(String(event.name ?? ''), (event.data as Record<string, unknown>) ?? {});
        } else if (event.type === 'done') {
          const payload = (event as { data?: { turn?: WritingTurn } }).data;
          const turn = payload?.turn;
          if (turn) callbacks.onDone?.(turn);
        }
      },
    }, { signal: options.signal });
  },

  async stopWritingTurn(novelId: number, requestId: string): Promise<WritingTurn> {
    const jobs = await generationJobsApi.list<WritingTurn>(novelId, 'chat');
    const job = jobs.find((item) => item.request_id === requestId);
    if (job) return jobTurn(await generationJobsApi.stop<WritingTurn>(novelId, job.id));
    return handleApiResponse(await enhancedFetch(`/writing-chat/${novelId}/turns/${requestId}/stop`, { method: 'POST' }));
  },
  async listStoryFacts(novelId: number, skip = 0, limit = 20, options: RequestOptions = {}): Promise<StoryFact[]> {
    return handleApiResponse(await enhancedFetch(`/story-bible/facts?novel_id=${novelId}&skip=${skip}&limit=${limit}`, options));
  },

  async createStoryFact(data: StoryFactCreate): Promise<StoryFact> {
    return handleApiResponse(await enhancedFetch('/story-bible/facts', { method: 'POST', body: JSON.stringify(data) }));
  },

  async updateStoryFact(id: number, data: StoryFactUpdate): Promise<StoryFact> {
    return handleApiResponse(await enhancedFetch(`/story-bible/facts/${id}`, { method: 'PUT', body: JSON.stringify(data) }));
  },

  async deleteStoryFact(id: number): Promise<void> {
    return handleApiResponse(await enhancedFetch(`/story-bible/facts/${id}`, { method: 'DELETE' }));
  },

  async listStoryEvents(novelId: number, skip = 0, limit = 20, options: RequestOptions = {}): Promise<StoryEvent[]> {
    return handleApiResponse(await enhancedFetch(`/story-bible/events?novel_id=${novelId}&skip=${skip}&limit=${limit}`, options));
  },

  async createStoryEvent(data: StoryEventCreate): Promise<StoryEvent> {
    return handleApiResponse(await enhancedFetch('/story-bible/events', { method: 'POST', body: JSON.stringify(data) }));
  },

  async updateStoryEvent(id: number, data: StoryEventUpdate): Promise<StoryEvent> {
    return handleApiResponse(await enhancedFetch(`/story-bible/events/${id}`, { method: 'PUT', body: JSON.stringify(data) }));
  },

  async deleteStoryEvent(id: number): Promise<void> {
    return handleApiResponse(await enhancedFetch(`/story-bible/events/${id}`, { method: 'DELETE' }));
  },

  async exportNovelText(novelId: number): Promise<Blob> {
    const response = await enhancedFetch(`/novels/${novelId}/export.txt`);
    if (!response.ok) await handleApiResponse(response);
    return response.blob();
  },
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
    const res = await enhancedFetch(`/novels/`, {
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
    const res = await enhancedFetch(`/novels/`, {
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
  async updateNovel(id: number, data: Partial<NovelCreate> & { review_mode?: 'confirm' | 'auto' | 'none' }): Promise<Novel> {
    const res = await enhancedFetch(`/novels/${id}`, {
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
    const res = await enhancedFetch(`/novels/${id}`, {
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
    const res = await enhancedFetch(`/novels/${novelId}/chapters`, {
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
    const res = await enhancedFetch(`/novels/${novelId}/chapters/${chapterId}`, {
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
    stage_outputs?: Array<Record<string, unknown>> | {
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
    const res = await enhancedFetch(`/generation/continue`, {
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
      const res = await enhancedFetch(`/generation/continue-stream`, {
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
    const res = await enhancedFetch(`/style/samples?novel_id=${novelId}`, {
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
    const res = await enhancedFetch(`/style/samples`, {
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
    const res = await enhancedFetch(`/generation/outline`, {
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
    const res = await enhancedFetch(`/generation/character`, {
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
    const res = await enhancedFetch(`/generation/init`, {
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

  /** 把作者一段自然语言想法解析为可编辑结构化草案，不创建小说。 */
  async parseIdea(data: { idea: string; planned_chapters?: number }): Promise<IdeaParseResult> {
    const res = await enhancedFetch(`/generation/parse-idea`, {
      method: 'POST', headers: getHeaders(), body: JSON.stringify(data),
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(extractApiErrorMessage(error, 'AI 解析想法失败'));
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
    const res = await enhancedFetch(`/generation/plot-options`, {
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
   * 局部文本改写
   */
  async rewriteText(data: {
    novel_id: number;
    chapter_id?: number;
    original_text: string;
    rewrite_type?: 'polish' | 'rewrite' | 'shorten' | 'extend';
    style_hint?: string;
    target_length?: number;
  }, options: RequestOptions = {}): Promise<{ rewritten_text: string }> {
    const res = await enhancedFetch(`/generation/rewrite`, {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify(data),
      signal: options.signal,
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
      const res = await enhancedFetch(`/consistency/check-stream`, {
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
    const res = await enhancedFetch(`/research/search`, {
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
