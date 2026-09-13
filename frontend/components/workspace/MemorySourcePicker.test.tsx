import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { chapterMemoryApi } from '@/lib/chapterMemory';
import type { ChapterRevision } from '@/types/chapterMemory';
import MemorySourcePicker from './MemorySourcePicker';
const revision: ChapterRevision = { id: 'revision-one', chapter_id: 2, chapter_number: 1, title: '城门', content: '😀。借剑。借剑。', version: 3, content_hash: 'hash', created_at: '' };
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
describe('记忆原文出处选择', () => {
  it('重复原句按明确位置选择，使用 Unicode 字符偏移', async () => {
    vi.spyOn(chapterMemoryApi, 'listRevisions').mockResolvedValue([revision]);
    vi.spyOn(chapterMemoryApi, 'getRevision').mockResolvedValue(revision);
    const onChange = vi.fn();
    render(<MemorySourcePicker novelId={1} chapterId={2} onChange={onChange} />);
    fireEvent.change(await screen.findByLabelText('引用原句'), { target: { value: '借剑' } });
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith({ revision_id: 'revision-one', quote: '借剑', start: 2 }, 'revision-one'));
    fireEvent.mouseDown(screen.getByLabelText('引用哪一处'));
    fireEvent.click(screen.getByRole('option', { name: '第 2 处' }));
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith({ revision_id: 'revision-one', quote: '借剑', start: 5 }, 'revision-one'));
  });
  it('切章后旧原文迟到不能成为新候选出处', async () => {
    let complete!: (value: ChapterRevision) => void;
    vi.spyOn(chapterMemoryApi, 'listRevisions').mockResolvedValueOnce([revision]).mockResolvedValueOnce([]);
    const read = vi.spyOn(chapterMemoryApi, 'getRevision').mockImplementation(() => new Promise((resolve) => { complete = resolve; }));
    const onChange = vi.fn();
    const { rerender } = render(<MemorySourcePicker novelId={1} chapterId={2} onChange={onChange} />);
    await waitFor(() => expect(read).toHaveBeenCalledTimes(1));
    const signal = read.mock.calls[0][2]!;
    rerender(<MemorySourcePicker novelId={1} chapterId={3} onChange={onChange} />);
    await act(async () => complete(revision));
    expect(signal.aborted).toBe(true);
    expect(screen.queryByLabelText('引用原句')).toBeNull();
    expect(onChange).toHaveBeenLastCalledWith(null, null);
  });
});
