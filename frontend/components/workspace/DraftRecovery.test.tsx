import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { RecoverableDraft } from '@/lib/chapterDrafts';
import DraftRecovery from './DraftRecovery';
const draft: RecoverableDraft = { storageKey: 'old-key', reason: 'legacy', draft: { novelId: 1, chapterId: 2, title: '待核对草稿', content: '尚未恢复的正文', version: 1, savedAt: '2026-01-01' } };
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.clear(); });
describe('本机草稿恢复入口', () => {
  it('旧稿仅供显式导出，导出后仍保留原备份', () => {
    localStorage.setItem(draft.storageKey, JSON.stringify(draft.draft));
    const createObjectURL = vi.fn(() => 'blob:recovery');
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    render(<DraftRecovery drafts={[draft]} />);
    fireEvent.click(screen.getByRole('button', { name: '有 1 份本机草稿等待核对' }));
    expect(screen.queryByText(draft.draft.content)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '导出恢复草稿' }));
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(click).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem(draft.storageKey)).toContain(draft.draft.content);
  });
  it('其他账号草稿不展示内容或标题，提示切回原账号导出', () => {
    render(<DraftRecovery drafts={[{ ...draft, reason: 'different_account' }]} />);
    fireEvent.click(screen.getByRole('button', { name: '有 1 份本机草稿等待核对' }));
    expect(screen.getByText('其他账号的草稿，请切回原账号导出')).toBeTruthy();
    expect(screen.queryByText(draft.draft.title)).toBeNull();
    expect((screen.getByRole('button', { name: '导出恢复草稿' }) as HTMLButtonElement).disabled).toBe(true);
  });
});
