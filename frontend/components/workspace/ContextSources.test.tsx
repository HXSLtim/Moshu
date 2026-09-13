import React from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { chapterMemoryApi } from '@/lib/chapterMemory';
import type { ChapterRevision } from '@/types/chapterMemory';
import type { ContextManifest } from '@/types/context';
import ContextSources from './ContextSources';

const source = { kind: 'chapter_digest' as const, id: 'digest-1', title: '风雪夜', chapter_id: 10, chapter_number: 1, source_revision_id: 'revision-1', source_version: 3, content_hash: 'source-hash' };
const manifest: ContextManifest = { version: 1, scope: { novel_id: 1, novel_lifecycle_id: 'novel-one', target_chapter: 3, current_day: null }, sources: [source], warnings: [], omitted: { missing: 1 }, fingerprint: 'private-fingerprint' };
const revision: ChapterRevision = { id: 'revision-1', version: 3, chapter_number: 1, title: '风雪夜', content_hash: 'source-hash', created_at: '', chapter_id: 10, content: '雪落在旧城门上。' };
const expand = () => fireEvent.click(screen.getByRole('button', { name: '本次参考简介' }));
const view = () => fireEvent.click(screen.getByRole('button', { name: '第 1 章 · 风雪夜 · 原文 v3' }));
beforeEach(() => { vi.spyOn(chapterMemoryApi, 'getRevision').mockResolvedValue(revision); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('对话参考简介来源', () => {
  it('旧轮缺少清单时不推断来源，空清单说明召回范围并显示可读警告', () => {
    const { rerender } = render(<ContextSources novelId={1} manifest={null} />);
    expect(screen.queryByText('本次参考简介')).toBeNull();
    rerender(<ContextSources novelId={1} manifest={{ ...manifest, sources: [], warnings: ['部分前文章节尚未提取简介。'] }} />);
    expand();
    expect(screen.getByText('暂无可用前文简介。')).toBeTruthy();
    expect(screen.getByText('部分前文章节尚未提取简介。')).toBeTruthy();
    expect(screen.queryByText('private-fingerprint')).toBeNull();
    expect(screen.queryByText('missing')).toBeNull();
    expect(chapterMemoryApi.getRevision).not.toHaveBeenCalled();
  });

  it('按生成时版本读取只读原文，不展示哈希或伪造简介', async () => {
    render(<ContextSources novelId={1} manifest={manifest} />);
    expand();
    view();
    await screen.findByText(revision.content);
    expect(chapterMemoryApi.getRevision).toHaveBeenCalledWith(1, source.source_revision_id, expect.any(AbortSignal));
    expect(screen.getByText(/只读历史原文，不会替换当前正文/)).toBeTruthy();
    expect(screen.queryByText('source-hash')).toBeNull();
  });

  it('关闭来源后打开另一份来源，旧请求迟到不能覆盖新内容', async () => {
    let completeFirst!: (value: ChapterRevision) => void;
    const second = { ...source, id: 'digest-2', title: '渡河', chapter_id: 11, chapter_number: 2, source_revision_id: 'revision-2', source_version: 4, content_hash: 'second-hash' };
    vi.mocked(chapterMemoryApi.getRevision).mockImplementationOnce(() => new Promise((resolve) => { completeFirst = resolve; })).mockResolvedValueOnce({ ...revision, id: second.source_revision_id, chapter_id: 11, chapter_number: 2, title: '渡河', version: 4, content_hash: 'second-hash', content: '他在渡口留下了玉佩。' });
    render(<ContextSources novelId={1} manifest={{ ...manifest, sources: [source, second] }} />);
    expand(); view();
    const firstSignal = vi.mocked(chapterMemoryApi.getRevision).mock.calls[0][2]!;
    fireEvent.click(screen.getByRole('button', { name: '关闭原文' }));
    fireEvent.click(await screen.findByRole('button', { name: '第 2 章 · 渡河 · 原文 v4' }));
    await screen.findByText('他在渡口留下了玉佩。');
    await act(async () => completeFirst(revision));
    expect(firstSignal.aborted).toBe(true);
    expect(screen.queryByText(revision.content)).toBeNull();
    expect(screen.getByText('他在渡口留下了玉佩。')).toBeTruthy();
  });

  it('切小说取消来源读取，作品范围不一致时禁止请求', async () => {
    let complete!: (value: ChapterRevision) => void;
    vi.mocked(chapterMemoryApi.getRevision).mockImplementation(() => new Promise((resolve) => { complete = resolve; }));
    const { rerender } = render(<ContextSources novelId={1} manifest={manifest} />);
    expand(); view();
    const signal = vi.mocked(chapterMemoryApi.getRevision).mock.calls[0][2]!;
    rerender(<ContextSources novelId={2} manifest={manifest} />);
    await act(async () => complete(revision));
    expect(signal.aborted).toBe(true);
    expect(screen.queryByText(revision.content)).toBeNull();
    expect(screen.getByText('来源记录与当前作品不一致，无法查看。')).toBeTruthy();
    expect(chapterMemoryApi.getRevision).toHaveBeenCalledTimes(1);
  });

  it('关闭和卸载都取消未完成的来源请求', async () => {
    vi.mocked(chapterMemoryApi.getRevision).mockImplementation(() => new Promise(() => {}));
    const { unmount } = render(<ContextSources novelId={1} manifest={manifest} />);
    expand(); view();
    const firstSignal = vi.mocked(chapterMemoryApi.getRevision).mock.calls[0][2]!;
    fireEvent.click(screen.getByRole('button', { name: '关闭原文' }));
    expect(firstSignal.aborted).toBe(true);
    fireEvent.click(await screen.findByRole('button', { name: '第 1 章 · 风雪夜 · 原文 v3' }));
    const secondSignal = vi.mocked(chapterMemoryApi.getRevision).mock.calls[1][2]!;
    unmount();
    expect(secondSignal.aborted).toBe(true);
  });

  it('拒绝与记录不符的来源版本', async () => {
    vi.mocked(chapterMemoryApi.getRevision).mockResolvedValue({ ...revision, version: 4, content: '不匹配的新正文' });
    render(<ContextSources novelId={1} manifest={manifest} />);
    expand(); view();
    await screen.findByText('来源版本与本次参考记录不一致，暂时无法展示。');
    expect(screen.queryByText('不匹配的新正文')).toBeNull();
  });
});
