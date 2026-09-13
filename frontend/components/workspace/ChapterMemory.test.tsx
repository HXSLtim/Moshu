import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { chapterMemoryApi } from '@/lib/chapterMemory';
import type { ChapterDigestStatus, ChapterRevision } from '@/types/chapterMemory';
import ChapterMemory from './ChapterMemory';

const props = { novelId: 1, chapterId: 2, currentVersion: 3 };
const ready: ChapterDigestStatus = {
  status: 'ready', current_version: 3, worker_enabled: true, job: null,
  digest: { id: 'digest-3', source_revision_id: 'revision-3', source_version: 3, summary: '少年进入城门。', participants: ['少年'], events: ['进城'], state_change_candidates: ['玉佩交给守门人'], open_threads: ['城门的符文'], source_refs: [{ revision_id: 'revision-3', start: 0, end: 5, quote: '少年推开门', content_hash: 'hash' }], created_at: '2026-09-08' },
};
const source: ChapterRevision = { id: 'revision-3', chapter_id: 2, chapter_number: 1, title: '城门', version: 3, content: '少年推开门，将玉佩交给守门人。', content_hash: 'hash', created_at: '2026-09-08' };
const pending = { id: 'job-3', state: 'queued' as const, attempts: 0, max_attempts: 3, error_code: null, error_message: null };
beforeEach(() => {
  vi.spyOn(chapterMemoryApi, 'getDigest').mockResolvedValue(ready);
  vi.spyOn(chapterMemoryApi, 'getRevision').mockResolvedValue(source);
  vi.spyOn(chapterMemoryApi, 'listRevisions').mockResolvedValue([source]);
  vi.spyOn(chapterMemoryApi, 'rebuild').mockResolvedValue(pending);
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });
const open = () => fireEvent.click(screen.getByRole('button', { name: '章节记忆' }));

describe('章节记忆工具区', () => {
  it('展开才读取，候选设定有明确标记且可只读回查原文', async () => {
    render(<ChapterMemory {...props} />);
    expect(chapterMemoryApi.getDigest).not.toHaveBeenCalled();
    open();
    await screen.findByText('少年进入城门。');
    expect(screen.getByText('状态变化候选（未确认为设定）')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '查看简介来源原文' }));
    await screen.findByText(source.content);
    expect(chapterMemoryApi.getRevision).toHaveBeenCalledWith(1, 'revision-3', expect.any(AbortSignal));
    expect(screen.queryByRole('button', { name: /恢复|覆盖|采纳/ })).toBeNull();
  });
  it('切章忽略迟到的简介响应和来源原文响应', async () => {
    let resolveDigest!: (value: ChapterDigestStatus) => void;
    vi.mocked(chapterMemoryApi.getDigest).mockImplementationOnce(() => new Promise((resolve) => { resolveDigest = resolve; }));
    const { rerender } = render(<ChapterMemory {...props} />);
    open();
    rerender(<ChapterMemory {...props} chapterId={4} />);
    await screen.findByText(ready.digest!.summary);
    await act(async () => resolveDigest({ ...ready, digest: { ...ready.digest!, summary: '旧章节迟到简介' } }));
    expect(screen.queryByText('旧章节迟到简介')).toBeNull();
    let resolveSource!: (value: ChapterRevision) => void;
    vi.mocked(chapterMemoryApi.getRevision).mockImplementationOnce(() => new Promise((resolve) => { resolveSource = resolve; }));
    fireEvent.click(screen.getByRole('button', { name: '查看简介来源原文' }));
    rerender(<ChapterMemory {...props} chapterId={5} />);
    await act(async () => resolveSource({ ...source, content: '旧章迟到的正文' }));
    expect(screen.queryByText('旧章迟到的正文')).toBeNull();
    expect(screen.queryByRole('dialog')).toBeNull();
  });
  it('失败保留旧简介，重建仅提交章节标识并提示来源于已保存稿', async () => {
    vi.mocked(chapterMemoryApi.getDigest).mockResolvedValue({ ...ready, status: 'stale', current_version: 4, job: { ...pending, state: 'failed', error_message: '模型输出不完整' } });
    render(<ChapterMemory {...props} currentVersion={4} />);
    open();
    await screen.findByText('简介提取失败：模型输出不完整');
    expect(screen.getByText('简介已过期，以下内容来自旧版本。')).toBeTruthy();
    expect(screen.getByText(/重建只读取已保存正文/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '重建简介' }));
    await waitFor(() => expect(chapterMemoryApi.getDigest).toHaveBeenCalledTimes(2));
    expect(chapterMemoryApi.rebuild).toHaveBeenCalledWith(1, 2, expect.any(AbortSignal));
    vi.mocked(chapterMemoryApi.getDigest).mockRejectedValueOnce(new Error('网络不可用'));
    fireEvent.click(screen.getByRole('button', { name: '刷新记忆' }));
    await screen.findByText('网络不可用');
    expect(screen.getByText(ready.digest!.summary)).toBeTruthy();
  });
  it('未启用 worker 时诚实展示排队状态且不轮询', async () => {
    vi.useFakeTimers();
    vi.mocked(chapterMemoryApi.getDigest).mockResolvedValue({ status: 'missing', current_version: 3, worker_enabled: false, digest: null, job: pending });
    render(<ChapterMemory {...props} />);
    await act(async () => open());
    expect(screen.getByText('自动提取未启用；提取任务会保留在队列中。')).toBeTruthy();
    await act(async () => { await vi.advanceTimersByTimeAsync(200000); });
    expect(chapterMemoryApi.getDigest).toHaveBeenCalledTimes(1);
  });
  it('提取轮询有次数上限，折叠会取消待处理请求', async () => {
    vi.useFakeTimers();
    vi.mocked(chapterMemoryApi.getDigest).mockResolvedValue({ ...ready, job: pending });
    render(<ChapterMemory {...props} />);
    await act(async () => open());
    await act(async () => { await vi.advanceTimersByTimeAsync(124000); });
    expect(chapterMemoryApi.getDigest).toHaveBeenCalledTimes(61);
    expect(screen.getByText(/本次自动刷新已暂停/)).toBeTruthy();
    await act(async () => { await vi.advanceTimersByTimeAsync(20000); });
    expect(chapterMemoryApi.getDigest).toHaveBeenCalledTimes(61);
    const signal = vi.mocked(chapterMemoryApi.getDigest).mock.calls.at(-1)![2]!;
    await act(async () => open());
    expect(signal.aborted).toBe(true);
  });
  it('版本历史支持分页并按 revision 标识打开，保存版本更新后刷新简介', async () => {
    vi.mocked(chapterMemoryApi.listRevisions).mockResolvedValueOnce(Array.from({ length: 20 }, (_, index) => ({ ...source, id: `revision-${23 - index}`, version: 23 - index }))).mockResolvedValueOnce([{ ...source, version: 3 }]);
    const { rerender } = render(<ChapterMemory {...props} />);
    open();
    fireEvent.click(await screen.findByRole('button', { name: '查看原文历史' }));
    fireEvent.click(await screen.findByRole('button', { name: '加载更早版本' }));
    await waitFor(() => expect(chapterMemoryApi.listRevisions).toHaveBeenLastCalledWith(1, 2, 4, expect.any(AbortSignal)));
    fireEvent.click(await screen.findByRole('button', { name: 'v3 · 城门' }));
    await screen.findByText(source.content);
    rerender(<ChapterMemory {...props} currentVersion={4} />);
    await waitFor(() => expect(chapterMemoryApi.getDigest).toHaveBeenCalledTimes(2));
    expect(screen.getByText('简介已过期，以下内容来自旧版本。')).toBeTruthy();
  });
  it('恢复须显式确认且发送当前版本和作品章节生命周期', async () => {
    const restored = { id: 2, novel_id: 1, chapter_number: 1, title: source.title, content: source.content, version: 4, word_count: 16, created_at: '', updated_at: '' };
    const restore = vi.spyOn(chapterMemoryApi, 'restoreRevision').mockImplementation(async () => {
      vi.mocked(chapterMemoryApi.listRevisions).mockResolvedValue([{ ...source, id: 'revision-4', version: 4 }, source]);
      return restored;
    });
    const onVersionRestored = vi.fn();
    render(<ChapterMemory {...props} novelLifecycleId="作品身份" chapterLifecycleId="章节身份" canRestore currentContent="当前稿" onVersionRestored={onVersionRestored} />);
    open();
    fireEvent.click(await screen.findByRole('button', { name: '查看原文历史' }));
    fireEvent.click(await screen.findByRole('button', { name: 'v3 · 城门' }));
    fireEvent.click(await screen.findByRole('button', { name: '恢复为新版本' }));
    expect(restore).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '确认恢复并保存' }));
    await waitFor(() => expect(onVersionRestored).toHaveBeenCalledWith(restored));
    expect(restore).toHaveBeenCalledWith(1, 'revision-3', { expected_version: 3, expected_novel_lifecycle_id: '作品身份', expected_chapter_lifecycle_id: '章节身份' }, expect.any(AbortSignal));
    await screen.findByRole('button', { name: 'v4 · 城门' });
  });
  it('恢复等待期间再编辑时保留新稿，冲突后保留来源原文', async () => {
    let finish!: (value: Awaited<ReturnType<typeof chapterMemoryApi.restoreRevision>>) => void;
    const restore = vi.spyOn(chapterMemoryApi, 'restoreRevision').mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    const onVersionRestored = vi.fn();
    const bound = { ...props, novelLifecycleId: '作品身份', chapterLifecycleId: '章节身份', canRestore: true, currentContent: '当前稿', onVersionRestored };
    const { rerender } = render(<ChapterMemory {...bound} />);
    open();
    fireEvent.click(await screen.findByRole('button', { name: '查看简介来源原文' }));
    fireEvent.click(await screen.findByRole('button', { name: '恢复为新版本' }));
    fireEvent.click(screen.getByRole('button', { name: '确认恢复并保存' }));
    await waitFor(() => expect(restore).toHaveBeenCalled());
    rerender(<ChapterMemory {...bound} canRestore={false} currentContent="恢复期间的新稿" />);
    await act(async () => finish({ id: 2, novel_id: 1, chapter_number: 1, title: source.title, content: source.content, version: 4, word_count: 16, created_at: '', updated_at: '' }));
    await screen.findByText(/本机新稿已保留/);
    expect(onVersionRestored).not.toHaveBeenCalled();
    expect(screen.getByText(source.content)).toBeTruthy();
  });
  it('取消简介提取调用持久任务接口并显示返回终态', async () => {
    vi.mocked(chapterMemoryApi.getDigest).mockResolvedValue({ ...ready, job: pending });
    const cancel = vi.spyOn(chapterMemoryApi, 'cancelJob').mockImplementation(async () => {
      const job = { ...pending, state: 'cancelled' as const };
      vi.mocked(chapterMemoryApi.getDigest).mockResolvedValue({ ...ready, job });
      return job;
    });
    render(<ChapterMemory {...props} />);
    open();
    fireEvent.click(await screen.findByRole('button', { name: '取消简介提取' }));
    await screen.findByText('简介提取已取消，可在需要时重新排队。');
    expect(cancel).toHaveBeenCalledWith('job-3', expect.any(AbortSignal));
    expect(screen.queryByRole('button', { name: '取消简介提取' })).toBeNull();
  });
});
