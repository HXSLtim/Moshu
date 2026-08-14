export type SSEEvent =
  | { type: 'chunk'; content: string }
  | { type: 'metadata'; data: unknown }
  | { type: 'done' }
  | { type: 'error'; message?: string }
  | { type: string; [key: string]: unknown };

export interface SSECallbacks {
  /** 收到任意原始事件时的回调 */
  onEvent?: (event: SSEEvent) => void;
  /** 收到文本块事件时的回调 */
  onChunk?: (content: string) => void;
  /** 收到元数据事件时的回调 */
  onMetadata?: (metadata: unknown) => void;
  /** 仅在收到明确的 done 事件后调用 */
  onDone?: () => void;
}

export interface SSEReadOptions {
  signal?: AbortSignal;
}

export class SSEUnexpectedEOFError extends Error {
  constructor() {
    super('SSE 流在完成事件到达前中断');
    this.name = 'SSEUnexpectedEOFError';
  }
}

function createAbortError(reason?: unknown): DOMException {
  const message = reason instanceof Error ? reason.message : '请求已取消';
  return new DOMException(message, 'AbortError');
}

function parseEventBlock(block: string): SSEEvent | null {
  const dataLines = block
    .split(/\r?\n/)
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trimStart());

  if (dataLines.length === 0) return null;

  const payload = dataLines.join('\n');
  try {
    return JSON.parse(payload) as SSEEvent;
  } catch (error) {
    throw new Error(
      `SSE 数据解析失败：${error instanceof Error ? error.message : '未知错误'}`,
    );
  }
}

/**
 * 读取由 fetch 返回的 SSE 流。
 *
 * 生成类请求不能把普通 EOF 当成成功，否则网络中断会被界面误报为完成。
 */
export async function readSSEFromResponse(
  res: Response,
  callbacks: SSECallbacks,
  options: SSEReadOptions = {},
): Promise<void> {
  if (!res.body) {
    throw new Error('SSE 响应没有 body');
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  const { signal } = options;
  let buffer = '';
  let receivedDone = false;

  const handleAbort = () => {
    void reader.cancel(signal?.reason).catch(() => undefined);
  };

  if (signal?.aborted) {
    await reader.cancel(signal.reason).catch(() => undefined);
    throw createAbortError(signal.reason);
  }
  signal?.addEventListener('abort', handleAbort, { once: true });

  const dispatch = (event: SSEEvent | null): boolean => {
    if (!event) return false;

    callbacks.onEvent?.(event);
    if (event.type === 'chunk' && typeof event.content === 'string') {
      callbacks.onChunk?.(event.content);
    } else if (event.type === 'metadata') {
      callbacks.onMetadata?.(event.data);
    } else if (event.type === 'done') {
      receivedDone = true;
      callbacks.onDone?.();
      return true;
    } else if (event.type === 'error') {
      throw new Error(
        `SSE 后端错误：${typeof event.message === 'string' ? event.message : '未知错误'}`,
      );
    }
    return false;
  };

  try {
    while (!receivedDone) {
      if (signal?.aborted) throw createAbortError(signal.reason);

      const { done, value } = await reader.read();
      if (signal?.aborted) throw createAbortError(signal.reason);

      if (done) {
        buffer += decoder.decode();
        const trailing = buffer.trim();
        if (trailing && dispatch(parseEventBlock(trailing))) {
          await reader.cancel().catch(() => undefined);
          return;
        }
        throw new SSEUnexpectedEOFError();
      }

      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split(/\r?\n\r?\n/);
      buffer = blocks.pop() ?? '';

      for (const block of blocks) {
        if (dispatch(parseEventBlock(block))) {
          await reader.cancel().catch(() => undefined);
          return;
        }
      }
    }
  } finally {
    signal?.removeEventListener('abort', handleAbort);
    reader.releaseLock();
  }
}
