import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from './api';
import { chapterMemoryApi } from './chapterMemory';

afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); });

describe('章节记忆 API', () => {
  it('复用鉴权与请求取消，重建不携带编辑器正文', async () => {
    localStorage.setItem('token', 'test-token');
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 202 }));
    vi.stubGlobal('fetch', fetchMock);
    const controller = new AbortController();
    await chapterMemoryApi.rebuild(2, 8, controller.signal);
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/api/novels/2/chapters/8/digest/rebuild'), expect.objectContaining({ method: 'POST', signal: controller.signal, headers: expect.objectContaining({ Authorization: 'Bearer test-token' }) }));
    expect(fetchMock.mock.calls[0][1].body).toBeUndefined();
  });
  it('保留服务端错误状态与文案', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: '无权访问此小说' }), { status: 403 })));
    await expect(chapterMemoryApi.getDigest(2, 8)).rejects.toEqual(new ApiError('无权访问此小说', 403));
  });
});
