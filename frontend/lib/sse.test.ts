// @vitest-environment node

import { describe, expect, it, vi } from 'vitest';
import {
  readSSEFromResponse,
  SSEUnexpectedEOFError,
} from './sse';

function createResponse(...frames: string[]): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const frame of frames) controller.enqueue(encoder.encode(frame));
        controller.close();
      },
    }),
  );
}

describe('readSSEFromResponse', () => {
  it('只有收到明确的 done 事件才完成', async () => {
    const onChunk = vi.fn();
    const onDone = vi.fn();
    const response = createResponse(
      'data: {"type":"chunk","content":"第一段"}\n\n',
      'data: {"type":"done"}\n\n',
    );

    await readSSEFromResponse(response, { onChunk, onDone });

    expect(onChunk).toHaveBeenCalledWith('第一段');
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it('流结束但缺少 done 时报告异常', async () => {
    const onDone = vi.fn();
    const response = createResponse(
      'data: {"type":"chunk","content":"未完成"}\n\n',
    );

    await expect(readSSEFromResponse(response, { onDone })).rejects.toBeInstanceOf(
      SSEUnexpectedEOFError,
    );
    expect(onDone).not.toHaveBeenCalled();
  });

  it('AbortSignal 会取消读取且不触发完成回调', async () => {
    const onDone = vi.fn();
    const controller = new AbortController();
    const response = new Response(
      new ReadableStream({
        start(streamController) {
          streamController.enqueue(
            new TextEncoder().encode('data: {"type":"chunk","content":"部分"}\n\n'),
          );
        },
      }),
    );

    const reading = readSSEFromResponse(response, { onDone }, { signal: controller.signal });
    controller.abort();

    await expect(reading).rejects.toMatchObject({ name: 'AbortError' });
    expect(onDone).not.toHaveBeenCalled();
  });
});
