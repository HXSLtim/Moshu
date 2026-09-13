import React from 'react';
import { webcrypto } from 'node:crypto';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { generationJobsApi } from '@/lib/generationJobs';
import { writingProposalApi } from '@/lib/writingProposal';
import { contentHash } from '@/lib/writingChat';
import TextRewriter from './TextRewriter';

const props = { novelId: 1, chapterId: 2, novelLifecycleId: 'n1', chapterLifecycleId: 'c1', chapterVersion: 2, currentContent: '😀原文，原文', selectedText: '原文', selectionStart: 5, selectionEnd: 7, canApply: true, onError: vi.fn(), onProposalAccepted: vi.fn() };
const job = { id: 'job1', request_id: 'r1', novel_id: 1, novel_lifecycle_id: 'n1', chapter_id: 2, chapter_lifecycle_id: 'c1', kind: 'rewrite' as const, status: 'completed' as const, result: { rewritten_text: '改写后的候选', proposal_id: 'p1' }, error: null, created_at: '2026-09-08', finished_at: '2026-09-08' };
const proposal = { id: 'p1', status: 'pending' as const, novel_id: 1, novel_lifecycle_id: 'n1', chapter_id: 2, chapter_lifecycle_id: 'c1', operation: 'replace_selection' as const, base_version: 2, base_content_hash: '' };
beforeEach(async () => {
  vi.stubGlobal('crypto', webcrypto); proposal.base_content_hash = await contentHash(props.currentContent);
  vi.spyOn(generationJobsApi, 'list').mockResolvedValue([]);
  vi.spyOn(generationJobsApi, 'create').mockImplementation(async (data) => ({ ...job, request_id: data.request_id }));
  vi.spyOn(writingProposalApi, 'get').mockResolvedValue(proposal);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.clearAllMocks(); });
const generate = async () => { await waitFor(() => expect((screen.getByRole('button', { name: '开始润色优化' }) as HTMLButtonElement).disabled).toBe(false)); fireEvent.click(screen.getByRole('button', { name: '开始润色优化' })); await screen.findByLabelText('改写候选稿'); };

describe('局部改写服务端采纳', () => {
  it('重复原句按Unicode选区提交，作者编辑候选后确认新版本', async () => {
    const chapter = { id: 2, novel_id: 1, chapter_number: 1, title: '第一章', content: '😀原文，作者调整稿', version: 3, word_count: 10, created_at: '', updated_at: '' };
    const accept = vi.spyOn(writingProposalApi, 'accept').mockResolvedValue({ proposal: { ...proposal, status: 'accepted' }, chapter, audit_id: 'a1' });
    render(<TextRewriter {...props} />); await generate();
    expect(generationJobsApi.create).toHaveBeenCalledWith(expect.objectContaining({ kind: 'rewrite', payload: expect.objectContaining({ original_text: '原文', selection_start: 4, selection_end: 6, expected_chapter_lifecycle_id: 'c1' }) }), expect.any(AbortSignal));
    expect(accept).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('改写候选稿'), { target: { value: '作者调整稿' } });
    await waitFor(() => expect((screen.getByRole('button', { name: '采纳并替换原选区' }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: '采纳并替换原选区' }));
    await screen.findByText('已采纳');
    expect(accept).toHaveBeenCalledWith(1, 'p1', expect.objectContaining({ candidate_content: '作者调整稿', expected_version: 2 }), expect.any(AbortSignal));
    expect(props.onProposalAccepted).toHaveBeenCalledWith(chapter);
  });
  it('生成后正文变化阻止替换并保留候选', async () => {
    const { rerender } = render(<TextRewriter {...props} />); await generate();
    rerender(<TextRewriter {...props} currentContent="后续新稿" canApply={false} />);
    await screen.findByText(/正文已发生变化，不能直接替换/);
    expect((screen.getByRole('button', { name: '采纳并替换原选区' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByLabelText('改写候选稿') as HTMLTextAreaElement).value).toBe(job.result.rewritten_text);
  });
  it('切作品丢弃迟到任务响应，并取消本页读取', async () => {
    let finish!: (value: typeof job) => void;
    const create = vi.mocked(generationJobsApi.create).mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    const { rerender } = render(<TextRewriter {...props} />);
    await waitFor(() => expect((screen.getByRole('button', { name: '开始润色优化' }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: '开始润色优化' }));
    await waitFor(() => expect(create).toHaveBeenCalled());
    rerender(<TextRewriter {...props} novelId={3} novelLifecycleId="n3" />);
    await act(async () => finish(job));
    expect(create.mock.calls[0][1]?.aborted).toBe(true);
    expect(screen.queryByLabelText('改写候选稿')).toBeNull();
  });
});
