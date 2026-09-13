import React from 'react';
import { webcrypto } from 'node:crypto';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { generationJobsApi } from '@/lib/generationJobs';
import { writingProposalApi } from '@/lib/writingProposal';
import { contentHash } from '@/lib/writingChat';
import AiWritingAssistant from './AiWritingAssistant';

const props = { novelId: 1, chapterId: 2, novelLifecycleId: 'n1', chapterLifecycleId: 'c1', chapterVersion: 2, currentContent: '当前正文', canApply: true, onError: vi.fn(), onProposalAccepted: vi.fn() };
const job = { id: 'job1', request_id: 'r1', novel_id: 1, novel_lifecycle_id: 'n1', chapter_id: 2, chapter_lifecycle_id: 'c1', kind: 'continue' as const, status: 'completed' as const, result: { content: '需要保留的生成稿', proposal_id: 'p1' }, error: null, created_at: '2026-09-08', finished_at: '2026-09-08' };
const chapter = { id: 2, novel_id: 1, chapter_number: 1, title: '第一章', content: '服务端保存稿', word_count: 6, version: 3, rag_lifecycle_id: 'c1', created_at: '', updated_at: '' };
const proposal = { id: 'p1', status: 'pending' as const, novel_id: 1, novel_lifecycle_id: 'n1', chapter_id: 2, chapter_lifecycle_id: 'c1', operation: 'append' as const, base_version: 2, base_content_hash: '' };
beforeEach(async () => {
  vi.stubGlobal('crypto', webcrypto);
  proposal.base_content_hash = await contentHash(props.currentContent);
  vi.spyOn(generationJobsApi, 'list').mockResolvedValue([]);
  vi.spyOn(generationJobsApi, 'create').mockResolvedValue(job);
  vi.spyOn(writingProposalApi, 'get').mockResolvedValue(proposal);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.clearAllMocks(); });
const generate = async () => { await waitFor(() => expect((screen.getByRole('button', { name: 'AI续写' }) as HTMLButtonElement).disabled).toBe(false)); fireEvent.click(screen.getByRole('button', { name: 'AI续写' })); await screen.findByText(job.result.content); };
const accept = async () => { await waitFor(() => expect((screen.getByRole('button', { name: '采纳到本章' }) as HTMLButtonElement).disabled).toBe(false)); fireEvent.click(screen.getByRole('button', { name: '采纳到本章' })); };

describe('高级续写持久任务与候选', () => {
  it('携带风格和来源提交持久任务，作者确认才通过服务端保存', async () => {
    const save = vi.spyOn(writingProposalApi, 'accept').mockResolvedValue({ proposal: { ...proposal, status: 'accepted' }, chapter, audit_id: 'a1' });
    render(<AiWritingAssistant {...props} />);
    await generate();
    expect(generationJobsApi.create).toHaveBeenCalledWith(expect.objectContaining({ kind: 'continue', expected_novel_lifecycle_id: 'n1', payload: expect.objectContaining({ chapter_id: 2, current_content: '当前正文', pace: 'medium', tone: 'neutral', expected_chapter_lifecycle_id: 'c1' }) }), expect.any(AbortSignal));
    expect(save).not.toHaveBeenCalled();
    await accept();
    await screen.findByText('已采纳');
    expect(props.onProposalAccepted).toHaveBeenCalledWith(chapter);
  });
  it('确认失败保留候选和幂等请求身份供重试', async () => {
    const save = vi.spyOn(writingProposalApi, 'accept').mockRejectedValueOnce(new Error('连接中断')).mockResolvedValueOnce({ proposal: { ...proposal, status: 'accepted' }, chapter, audit_id: 'a1' });
    render(<AiWritingAssistant {...props} />);
    await generate(); await accept();
    await screen.findByText('连接中断');
    expect(screen.getByText(job.result.content)).toBeTruthy();
    await accept(); await screen.findByText('已采纳');
    expect(save.mock.calls[0][2].request_id).toBe(save.mock.calls[1][2].request_id);
  });
  it('重开本章恢复排队任务，明确停止才取消服务端任务', async () => {
    vi.mocked(generationJobsApi.list).mockResolvedValue([{ ...job, status: 'queued', result: null }]);
    const stop = vi.spyOn(generationJobsApi, 'stop').mockResolvedValue({ ...job, status: 'cancelled', result: null });
    render(<AiWritingAssistant {...props} />);
    await screen.findByText('续写任务已排队');
    fireEvent.click(screen.getByRole('button', { name: '停止续写' }));
    await screen.findByText('续写任务已取消。');
    expect(stop).toHaveBeenCalledWith(1, 'job1', expect.any(AbortSignal));
  });
  it('一致性重试耗尽与未执行检查如实显示', async () => {
    vi.mocked(generationJobsApi.create).mockResolvedValue({ ...job, result: { ...job.result, final_consistency: { status: 'conflict_after_retries', has_conflict: true, retry_exhausted: true, is_complete: false, checks_skipped: ['knowledge_graph'], violations: ['人物年龄与前文设定不一致'] } } });
    render(<AiWritingAssistant {...props} />); await generate();
    expect(screen.getByText('一致性检查重试已耗尽，当前仍是冲突稿')).toBeTruthy();
    expect(screen.getByText('部分一致性检查未执行')).toBeTruthy();
    expect(screen.getByText('未执行：知识图谱')).toBeTruthy();
    expect(screen.getByText('· 人物年龄与前文设定不一致')).toBeTruthy();
  });
});
