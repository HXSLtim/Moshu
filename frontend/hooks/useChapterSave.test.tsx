import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/lib/api';
import type { Chapter } from '@/types';
import { useChapterSave } from './useChapterSave';

function chapter(content: string, version: number): Chapter {
  return {
    id: 10,
    rag_lifecycle_id: "chapter-life",
    novel_id: 1,
    chapter_number: 1,
    title: '第一章',
    content,
    word_count: content.length,
    version,
    created_at: '2026-07-10T00:00:00Z',
  };
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); localStorage.clear(); });

describe('useChapterSave', () => {
  it('保存中继续输入时串行提交最新快照，并递增 expected_version', async () => {
    const resolvers: Array<(value: Chapter) => void> = [];
    const updateSpy = vi.spyOn(api, 'updateChapter').mockImplementation(
      (_novelId, _chapterId, data) =>
        new Promise((resolve) => {
          resolvers.push((value) => resolve({ ...value, title: data.title ?? value.title }));
        }),
    );
    const onSaved = vi.fn();
    const initialChapter = chapter('旧稿', 1);
    const { result, rerender } = renderHook(
      ({ content }) =>
        useChapterSave({
          novelId: 1, userId: 7, novelLifecycleId: "novel-life",
          chapter: initialChapter,
          title: '第一章',
          content,
          autoSaveDelay: 60_000,
          onSaved,
        }),
      { initialProps: { content: '旧稿' } },
    );

    rerender({ content: '第一版' });
    let saving!: Promise<void>;
    act(() => {
      saving = result.current.saveNow('manual');
    });
    await waitFor(() => expect(updateSpy).toHaveBeenCalledTimes(1));

    rerender({ content: '最终版' });
    act(() => resolvers[0](chapter('第一版', 2)));
    await waitFor(() => expect(updateSpy).toHaveBeenCalledTimes(2));
    act(() => resolvers[1](chapter('最终版', 3)));
    await act(async () => saving);

    expect(updateSpy.mock.calls[0][2]).toMatchObject({
      content: '第一版',
      expected_version: 1,
    });
    expect(updateSpy.mock.calls[1][2]).toMatchObject({
      content: '最终版',
      expected_version: 2,
    });
    expect(onSaved).toHaveBeenLastCalledWith(
      expect.objectContaining({ content: '最终版', expectedVersion: 2 }),
      expect.objectContaining({ content: '最终版', version: 3 }),
      expect.any(Date),
    );
    expect(result.current.isDirty).toBe(false);
    expect(result.current.status).toBe('saved');
  });
});
