import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/lib/api';
import { chapterDraftKey, writeChapterDraft } from '@/lib/chapterDrafts';
import type { Chapter } from '@/types';
import { useChapterSave } from './useChapterSave';
const identity = { userId: 7, novelLifecycleId: 'novel-life', chapterLifecycleId: 'chapter-life' };
const chapter: Chapter = { id: 10, novel_id: 1, rag_lifecycle_id: 'chapter-life', chapter_number: 1, title: '城门', content: '当前原文', version: 3, word_count: 4, created_at: '', updated_at: '2026-01-01T00:00:00Z' };
const base = { novelId: 1, userId: 7, novelLifecycleId: 'novel-life', chapter, title: chapter.title, content: chapter.content, autoSaveDelay: 60000 };
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); localStorage.clear(); });

describe('草稿身份与删除重建保护', () => {
  it('旧格式与其他账号草稿保留为导出候选，不能静默载入或删除', () => {
    const old = { novelId: 1, chapterId: 10, title: '旧稿', content: '旧格式文字', version: 3, savedAt: new Date().toISOString() };
    localStorage.setItem('nai_chapter_draft_1_10', JSON.stringify(old));
    writeChapterDraft(1, { chapterId: 10, title: '他人稿', content: '他人文字' }, 3, { ...identity, userId: 99 });
    const onDraftRestored = vi.fn();
    const { result } = renderHook(() => useChapterSave({ ...base, onDraftRestored }));
    expect(onDraftRestored).not.toHaveBeenCalled();
    expect(result.current.recoveryDrafts.map((x) => x.reason).sort()).toEqual(['different_account', 'legacy']);
    expect(localStorage.length).toBe(2);
  });

  it('相同数字章节删除重建后不能恢复旧生命期草稿', () => {
    writeChapterDraft(1, { chapterId: 10, title: '旧章', content: '删除前的离线稿' }, 1, identity);
    const onDraftRestored = vi.fn();
    const { result } = renderHook(() => useChapterSave({ ...base, chapter: { ...chapter, version: 1, rag_lifecycle_id: 'replacement' }, onDraftRestored }));
    expect(onDraftRestored).not.toHaveBeenCalled();
    expect(result.current.recoveryDrafts[0].reason).toBe('different_lifecycle');
    expect(localStorage.getItem(chapterDraftKey(1, 10, identity))).toContain('删除前的离线稿');
  });

  it('同身份过时稿先归档，新编辑备份不能把它覆盖', () => {
    vi.useFakeTimers();
    writeChapterDraft(1, { chapterId: 10, title: chapter.title, content: '需要人工核对的旧稿' }, 2, identity);
    const { result, rerender } = renderHook(({ content }) => useChapterSave({ ...base, content }), { initialProps: { content: chapter.content } });
    const archivedKey = result.current.recoveryDrafts[0].storageKey;
    expect(archivedKey).toContain('_recovery_');
    rerender({ content: '本次编辑的新稿' });
    act(() => vi.advanceTimersByTime(600));
    expect(localStorage.getItem(archivedKey)).toContain('需要人工核对的旧稿');
    expect(localStorage.getItem(chapterDraftKey(1, 10, identity))).toContain('本次编辑的新稿');
  });

  it('作者或章节身份缺失时禁止保存，不发送缺少条件的写入', async () => {
    const update = vi.spyOn(api, 'updateChapter');
    const { result } = renderHook(() => useChapterSave({ ...base, userId: null }));
    await act(async () => { await expect(result.current.saveNow()).rejects.toThrow('身份尚未核验'); });
    expect(update).not.toHaveBeenCalled();
    expect(result.current.identityReady).toBe(false);
  });

  it('重建章节时取消旧保存，迟到回包不能确认或清除旧草稿', async () => {
    let complete!: (value: Chapter) => void;
    const update = vi.spyOn(api, 'updateChapter').mockImplementation(() => new Promise((resolve) => { complete = resolve; }));
    const onSaved = vi.fn();
    writeChapterDraft(1, { chapterId: 10, title: chapter.title, content: '旧章编辑' }, 3, identity);
    const { result, rerender } = renderHook(({ source, content }) => useChapterSave({ ...base, chapter: source, content, onSaved }), { initialProps: { source: chapter, content: chapter.content } });
    rerender({ source: chapter, content: '旧章编辑' });
    let saving!: Promise<void>;
    act(() => { saving = result.current.saveNow(); });
    expect(update.mock.calls[0][2]).toMatchObject({ expected_novel_lifecycle_id: 'novel-life', expected_chapter_lifecycle_id: 'chapter-life' });
    const signal = update.mock.calls[0][3]!.signal!;
    rerender({ source: { ...chapter, rag_lifecycle_id: 'replacement', content: '重建章', version: 1 }, content: '重建章' });
    await act(async () => { complete({ ...chapter, content: '旧章编辑', version: 4 }); await saving; });
    expect(signal.aborted).toBe(true);
    expect(onSaved).not.toHaveBeenCalled();
    expect(localStorage.getItem(chapterDraftKey(1, 10, identity))).toContain('旧章编辑');
    expect(result.current.isDirty).toBe(false);
  });
});
