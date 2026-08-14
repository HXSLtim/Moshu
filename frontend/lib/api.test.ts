import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from './api';

describe('API 请求取消', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('预期的 AbortError 直接透传且不记录网络错误', async () => {
    const abortError = new DOMException('切换页面取消请求', 'AbortError');
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    vi.spyOn(console, 'log').mockImplementation(() => undefined);
    vi.stubGlobal('localStorage', {
      getItem: vi.fn(() => '测试令牌'),
    });
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(abortError));

    await expect(api.getNovel(1)).rejects.toBe(abortError);
    expect(consoleError).not.toHaveBeenCalled();
  });

  it('FastAPI 校验错误显示可读字段信息而不是对象字符串', async () => {
    vi.stubGlobal('localStorage', { getItem: vi.fn(() => null) });
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: [
              {
                loc: ['body', 'email'],
                msg: 'value is not a valid email address',
                type: 'value_error',
              },
            ],
          }),
          { status: 422, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    );

    await expect(
      api.register({
        username: 'browser-qa',
        email: 'invalid',
        password: '123456',
      }),
    ).rejects.toThrow('email：value is not a valid email address');
  });
});
