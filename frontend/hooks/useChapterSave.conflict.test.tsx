import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '@/lib/api';
import type { Chapter } from '@/types';
import { useChapterSave } from './useChapterSave';
import { chapterDraftKey } from '@/lib/chapterDrafts';

function chapter(
  content: string,
  version: number,
  overrides: Partial<Chapter> = {},
): Chapter {
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
    updated_at: '2026-07-10T00:00:00Z',
    ...overrides,
  };
}

const identity = { userId: 7, novelLifecycleId: 'novel-life', chapterLifecycleId: 'chapter-life' };
const DRAFT_KEY = chapterDraftKey(1, 10, identity);

function setNavigatorOnline(online: boolean) {
  Object.defineProperty(window.navigator, 'onLine', {
    configurable: true,
    value: online,
  });
  window.dispatchEvent(new Event(online ? 'online' : 'offline'));
}

describe('useChapterSave 冲突与离线防护', () => {
  beforeEach(() => {
    localStorage.clear();
    setNavigatorOnline(true);
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it('409 时冻结自动保存并给出冲突详情', async () => {
    const updateSpy = vi
      .spyOn(api, 'updateChapter')
      .mockRejectedValue(
        new ApiError('章节已被其他保存更新，当前版本为5，请刷新后重试', 409),
      );
    const onConflict = vi.fn();
    const initialChapter = chapter('旧稿', 1);
    const { result, rerender } = renderHook(
      ({ content }) =>
        useChapterSave({
          novelId: 1, userId: 7, novelLifecycleId: "novel-life",
          chapter: initialChapter,
          title: '第一章',
          content,
          autoSaveDelay: 60_000,
          onConflict,
        }),
      { initialProps: { content: '旧稿' } },
    );

    rerender({ content: '本地新稿' });
    await act(async () => {
      await expect(result.current.saveNow('manual')).rejects.toMatchObject({
        status: 409,
      });
    });

    expect(result.current.conflict).toMatchObject({
      snapshot: {
        chapterId: 10,
        title: '第一章',
        content: '本地新稿',
        expectedVersion: 1,
      },
      serverVersion: 5,
    });
    expect(result.current.status).toBe('error');
    expect(onConflict).toHaveBeenCalledTimes(1);
    expect(updateSpy).toHaveBeenCalledTimes(1);
  });

  it('覆盖冲突时以服务端版本为 expected_version 重新保存', async () => {
    const updateSpy = vi
      .spyOn(api, 'updateChapter')
      .mockRejectedValueOnce(
        new ApiError('章节已被其他保存更新，当前版本为5，请刷新后重试', 409),
      );
    const { result, rerender } = renderHook(
      ({ content }) =>
        useChapterSave({
          novelId: 1, userId: 7, novelLifecycleId: "novel-life",
          chapter: chapter('旧稿', 1),
          title: '第一章',
          content,
          autoSaveDelay: 60_000,
        }),
      { initialProps: { content: '旧稿' } },
    );

    rerender({ content: '本地新稿' });
    await act(async () => {
      await expect(result.current.saveNow('manual')).rejects.toBeTruthy();
    });

    updateSpy.mockResolvedValueOnce(
      chapter('本地新稿', 6, { updated_at: '2026-07-10T00:01:00Z' }),
    );
    await act(async () => {
      await result.current.overwriteConflict();
    });

    expect(updateSpy.mock.calls[1][2]).toMatchObject({
      content: '本地新稿',
      expected_version: 5,
    });

    expect(result.current.conflict).toBeNull();
    expect(result.current.status).toBe('saved');
  });

  it('采纳服务端版本后本地编辑状态与版本基线同步', async () => {
    vi.spyOn(api, 'updateChapter').mockRejectedValueOnce(
      new ApiError('章节已被其他保存更新，当前版本为5，请刷新后重试', 409),
    );
    const serverChapter = chapter('服务端更新稿', 5, {
      updated_at: '2026-07-10T00:02:00Z',
    });
    const { result, rerender } = renderHook(
      ({ content, title }) =>
        useChapterSave({
          novelId: 1, userId: 7, novelLifecycleId: "novel-life",
          chapter: chapter('旧稿', 1),
          title,
          content,
          autoSaveDelay: 60_000,
        }),
      { initialProps: { content: '旧稿', title: '第一章' } },
    );

    rerender({ content: '本地新稿', title: '第一章' });
    await act(async () => {
      await expect(result.current.saveNow('manual')).rejects.toBeTruthy();
    });

    act(() => result.current.adoptServerChapter(serverChapter));
    rerender({ content: serverChapter.content, title: serverChapter.title });

    expect(result.current.conflict).toBeNull();
    expect(result.current.isDirty).toBe(false);
  });

  it('编辑中的草稿防抖写入 localStorage，保存成功后清除', async () => {
    vi.useFakeTimers();
    try {
      vi.spyOn(api, 'updateChapter').mockResolvedValue(
        chapter('本地新稿', 2, { updated_at: '2026-07-10T00:01:00Z' }),
      );
      const { result, rerender } = renderHook(
        ({ content }) =>
          useChapterSave({
            novelId: 1, userId: 7, novelLifecycleId: "novel-life",
            chapter: chapter('旧稿', 1),
            title: '第一章',
            content,
            autoSaveDelay: 60_000,
          }),
        { initialProps: { content: '旧稿' } },
      );

      rerender({ content: '本地新稿' });
      act(() => vi.advanceTimersByTime(600));
      expect(JSON.parse(localStorage.getItem(DRAFT_KEY) || '{}')).toMatchObject({
        chapterId: 10,
        content: '本地新稿',
      });
      expect(result.current.hasLocalBackup).toBe(true);

      await act(async () => {
        await result.current.saveNow('manual');
      });
      expect(localStorage.getItem(DRAFT_KEY)).toBeNull();
      expect(result.current.hasLocalBackup).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it('旧快照保存成功但新稿保存失败时，新稿本机备份仍保留', async () => {
    vi.useFakeTimers();
    try {
      let resolveFirst!: (value: Chapter) => void;
      vi.spyOn(api, 'updateChapter')
        .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }))
        .mockRejectedValueOnce(new Error('网络中断'));
      const initialChapter = chapter('旧稿', 1);
      const { result, rerender } = renderHook(({ content }) => useChapterSave({
        novelId: 1, userId: 7, novelLifecycleId: "novel-life", chapter: initialChapter, title: '第一章', content, autoSaveDelay: 60_000,
      }), { initialProps: { content: '旧稿' } });
      rerender({ content: '第一版' });
      let saving!: Promise<void>;
      act(() => { saving = result.current.saveNow('manual'); });
      rerender({ content: '尚未保存的新稿' });
      act(() => vi.advanceTimersByTime(600));
      expect(JSON.parse(localStorage.getItem(DRAFT_KEY) || '{}').content).toBe('尚未保存的新稿');
      await act(async () => {
        const failed = expect(saving).rejects.toThrow('网络中断');
        resolveFirst(chapter('第一版', 2));
        await failed;
      });
      expect(JSON.parse(localStorage.getItem(DRAFT_KEY) || '{}')).toMatchObject({
        content: '尚未保存的新稿', version: 2,
      });
      expect(result.current.hasLocalBackup).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it('离线时保留草稿，online 事件后自动重放保存', async () => {
    const updateSpy = vi
      .spyOn(api, 'updateChapter')
      .mockResolvedValue(
        chapter('离线草稿', 2, { updated_at: '2026-07-10T00:01:00Z' }),
      );
    const { result, rerender } = renderHook(
      ({ content }) =>
        useChapterSave({
          novelId: 1, userId: 7, novelLifecycleId: "novel-life",
          chapter: chapter('旧稿', 1),
          title: '第一章',
          content,
          autoSaveDelay: 60_000,
        }),
      { initialProps: { content: '旧稿' } },
    );

    rerender({ content: '离线草稿' });
    act(() => setNavigatorOnline(false));
    expect(result.current.status).toBe('offline');
    expect(updateSpy).not.toHaveBeenCalled();

    act(() => setNavigatorOnline(true));
    await waitFor(() => expect(updateSpy).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(result.current.status).toBe('saved'));
    expect(updateSpy.mock.calls[0][2]).toMatchObject({
      content: '离线草稿',
      expected_version: 1,
    });
  });

  it('本地草稿比服务端新时通过回调恢复', async () => {
    const draft = {
      novelId: 1, userId: 7, novelLifecycleId: "novel-life",
      chapterId: 10,
      title: '第一章',
      content: '崩溃前未保存的草稿',
      identity, schemaVersion: 2,
      version: 1,
      savedAt: '2026-07-10T00:05:00.000Z',
    };
    localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
    const onDraftRestored = vi.fn();
    const { result } = renderHook(() =>
      useChapterSave({
        novelId: 1, userId: 7, novelLifecycleId: "novel-life",
        chapter: chapter('服务端旧稿', 1),
        title: '第一章',
        content: '服务端旧稿',
        autoSaveDelay: 60_000,
        onDraftRestored,
      }),
    );

    await waitFor(() => expect(onDraftRestored).toHaveBeenCalledTimes(1));
    expect(onDraftRestored.mock.calls[0][0]).toMatchObject(draft);
    expect(result.current.isDirty).toBe(false);
  });
});
