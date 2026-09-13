import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/lib/api';
import type { User } from '@/types';
import { useAuthenticatedUser } from './useAuthenticatedUser';
const author: User = { id: 7, username: '作者', email: 'synthetic@example.test', is_active: true, created_at: '' };
afterEach(() => { cleanup(); vi.restoreAllMocks(); localStorage.clear(); });
describe('编辑器作者身份核验', () => {
  it('仅信任服务端认证结果，登出后立即撤销可用身份', async () => {
    localStorage.setItem('token', 'session-one'); localStorage.setItem('user', '{"id":999}');
    vi.spyOn(api, 'getCurrentUser').mockResolvedValue(author);
    const { result } = renderHook(() => useAuthenticatedUser());
    await waitFor(() => expect(result.current?.id).toBe(7));
    act(() => { localStorage.removeItem('token'); window.dispatchEvent(new Event('storage')); });
    expect(result.current).toBeNull();
  });
  it('账号切换时旧认证请求迟到不能恢复旧身份', async () => {
    let complete!: (user: User) => void;
    localStorage.setItem('token', 'session-one');
    vi.spyOn(api, 'getCurrentUser').mockImplementationOnce(() => new Promise((resolve) => { complete = resolve; })).mockResolvedValueOnce({ ...author, id: 8 });
    const { result } = renderHook(() => useAuthenticatedUser());
    act(() => { localStorage.setItem('token', 'session-two'); window.dispatchEvent(new Event('storage')); });
    await waitFor(() => expect(result.current?.id).toBe(8));
    await act(async () => complete(author));
    expect(result.current?.id).toBe(8);
  });
});
