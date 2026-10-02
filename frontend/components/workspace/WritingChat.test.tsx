import React from 'react';
import { webcrypto } from 'node:crypto';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/lib/api';
import { contentHash } from '@/lib/writingChat';
import { writingProposalApi } from '@/lib/writingProposal';
import { chapterMemoryApi } from '@/lib/chapterMemory';
import type { ContextManifest } from '@/types/context';
import type { WritingTurn } from '@/types/writingChat';
import WritingChat from './WritingChat';

const turn: WritingTurn = { id: 1, request_id: 'saved-turn', novel_id: 1, chapter_id: 2, chapter_title: '第一章', mode: 'continue', user_text: '请把玉佩作为伏笔', assistant_text: '城门与玉佩的纹路一致。', status: 'completed', base_content_hash: '', error: null, created_at: '2026-09-08T00:00:00' };
const props = { novelId: 1, chapterId: 2, chapterTitle: '第一章', currentContent: '当前正文', onContentGenerated: vi.fn() };
beforeEach(() => { vi.stubGlobal('crypto', webcrypto); vi.spyOn(api, 'listWritingTurns').mockResolvedValue([turn]); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.clearAllMocks(); });

describe('常驻对话面板', () => {
  it('历史恢复后可查看生成时参考的原文版本，来源删除不影响回复', async () => {
    const manifest: ContextManifest = { version: 1, scope: { novel_id: 1, novel_lifecycle_id: 'novel-one', target_chapter: 2, current_day: null }, sources: [{ kind: 'chapter_digest', id: 'digest-1', title: '前章旧标题', chapter_id: 1, chapter_number: 1, source_revision_id: 'revision-old', source_version: 2, content_hash: 'old-hash' }], warnings: [], omitted: {}, fingerprint: 'fixed' };
    vi.mocked(api.listWritingTurns).mockResolvedValue([{ ...turn, context_manifest: manifest }]);
    const getRevision = vi.spyOn(chapterMemoryApi, 'getRevision').mockResolvedValue({ id: 'revision-old', chapter_id: 1, chapter_number: 1, title: '前章旧标题', version: 2, content_hash: 'old-hash', content: '生成时的来源原文', created_at: '' });
    const { rerender } = render(<WritingChat {...props} />);
    await screen.findByText(turn.assistant_text);
    rerender(<WritingChat {...props} currentContent="本章已改写" />);
    fireEvent.click(screen.getByRole('button', { name: '本次参考简介' }));
    const sourceButton = screen.getByRole('button', { name: '第 1 章 · 前章旧标题 · 原文 v2' });
    fireEvent.click(sourceButton);
    await screen.findByText('生成时的来源原文');
    expect(getRevision).toHaveBeenCalledWith(1, 'revision-old', expect.any(AbortSignal));
    fireEvent.click(screen.getByRole('button', { name: '关闭原文' }));
    getRevision.mockRejectedValue(new Error('404 Not Found'));
    fireEvent.click(sourceButton);
    await screen.findByText('无法读取这份来源原文，可能已删除或暂时无法访问。对话回复仍然保留。');
    expect(screen.getByText(turn.assistant_text)).toBeTruthy();
    expect(props.onContentGenerated).not.toHaveBeenCalled();
  });

  it('旧对话没有清单时不声称已参考简介', async () => {
    render(<WritingChat {...props} />);
    await screen.findByText(turn.assistant_text);
    expect(screen.queryByText('本次参考简介')).toBeNull();
  });
  it('刷新组件能恢复历史，跨章保留交流并阻止采纳其他章节候选', async () => {
    const { rerender, unmount } = render(<WritingChat {...props} />);
    await screen.findByText(turn.assistant_text);
    rerender(<WritingChat {...props} chapterId={3} chapterTitle="第二章" />);
    expect(screen.getByText(turn.assistant_text)).toBeTruthy();
    expect((screen.getByRole('button', { name: '采纳到本章' }) as HTMLButtonElement).disabled).toBe(true);
    unmount();
    render(<WritingChat {...props} />);
    await screen.findByText(turn.user_text);
    expect(api.listWritingTurns).toHaveBeenCalledTimes(2);
  });
  it('发送讨论保留历史，并携带当前章节和未保存正文', async () => {
    const send = vi.spyOn(api, 'streamWritingTurn').mockImplementation(async (_id, data, callbacks) => {
      callbacks.onChunk?.('可以让守门人');
      callbacks.onChunk?.('认出玉佩。');
      callbacks.onDone?.({ ...turn, id: 2, request_id: data.request_id, user_text: data.message, mode: data.mode, assistant_text: '可以让守门人认出玉佩。' });
    });
    render(<WritingChat {...props} />);
    await screen.findByText(turn.assistant_text);
    fireEvent.change(screen.getByLabelText('和 Nai 聊聊'), { target: { value: '刚才的伏笔怎么回收？' } });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    await screen.findByText('可以让守门人认出玉佩。');
    expect(screen.getByText(turn.assistant_text)).toBeTruthy();
    expect(send).toHaveBeenCalledWith(1, expect.objectContaining({ chapter_id: 2, current_content: '当前正文', message: '刚才的伏笔怎么回收？', mode: 'discuss' }), expect.anything(), expect.anything());
    expect(props.onContentGenerated).not.toHaveBeenCalled();
  });
  it('失败问题留在记录里，允许重新编辑', async () => {
    vi.mocked(api.listWritingTurns).mockResolvedValue([{ ...turn, status: 'failed', assistant_text: '', error: '模型连接中断' }]);
    render(<WritingChat {...props} />);
    fireEvent.click(await screen.findByRole('button', { name: '重新编辑' }));
    await waitFor(() => expect((screen.getByLabelText('和 Nai 聊聊') as HTMLTextAreaElement).value).toBe(turn.user_text));
    expect(screen.getByText('模型连接中断')).toBeTruthy();
  });
  it('网络失败保留未送达的问题，不覆盖正在输入的下一条草稿', async () => {
    let rejectRequest!: (error: Error) => void;
    vi.spyOn(api, 'streamWritingTurn').mockImplementation(() => new Promise((_resolve, reject) => { rejectRequest = reject; }));
    render(<WritingChat {...props} />);
    await screen.findByText(turn.assistant_text);
    const input = screen.getByLabelText('和 Nai 聊聊');
    fireEvent.change(input, { target: { value: '未送达的问题' } });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    fireEvent.change(input, { target: { value: '正在写的下一条' } });
    rejectRequest(new Error('网络中断'));
    await screen.findByText('消息未保存到服务器，请重新发送。');
    expect(screen.getByText('未送达的问题')).toBeTruthy();
    expect((input as HTMLTextAreaElement).value).toBe('正在写的下一条');
  });
  it('交流不再让作者选意图，统一交给 Agent 判断', async () => {
    const send = vi.spyOn(api, 'streamWritingTurn').mockImplementation(async (_id, data, callbacks) => {
      callbacks.onDone?.({ ...turn, request_id: data.request_id, mode: 'discuss', assistant_text: 'Agent 回复' });
    });
    render(<WritingChat {...props} />); await screen.findByText(turn.assistant_text);
    expect(screen.queryByLabelText('意图')).toBeNull();
    expect(screen.getByText(/Nai 会自己判断该回答、整理设定还是起草正文/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('和 Nai 聊聊'), { target: { value: '设计借剑之后的悬念' } });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    await screen.findByText('Agent 回复');
    expect(send).toHaveBeenCalledWith(1, expect.objectContaining({ mode: 'discuss', message: '设计借剑之后的悬念' }), expect.anything(), expect.anything());
  });

});


describe('服务端候选确认', () => {
  it('来源版本匹配后调用服务端采纳，并使用服务端新版本更新编辑器', async () => {
    const accepted = vi.fn();
    const hash = await contentHash(props.currentContent);
    const proposal = { novel_id: 1, novel_lifecycle_id: 'n1', chapter_id: 2, chapter_lifecycle_id: 'c1', id: 'p1', status: 'pending' as const, operation: 'append' as const, base_version: 2, base_content_hash: hash };
    vi.mocked(api.listWritingTurns).mockResolvedValue([{ ...turn, base_content_hash: hash, proposal_id: 'p1', base_version: 2, novel_lifecycle_id: 'n1', chapter_lifecycle_id: 'c1' }]);
    vi.spyOn(writingProposalApi, 'get').mockResolvedValue(proposal);
    const chapter = { id: 2, novel_id: 1, chapter_number: 1, title: '第一章', content: '服务端保存后的正文', word_count: 10, version: 3, rag_lifecycle_id: 'c1', created_at: '', updated_at: '' };
    const accept = vi.spyOn(writingProposalApi, 'accept').mockResolvedValue({ proposal: { ...proposal, status: 'accepted' }, chapter, audit_id: 'a1' });
    render(<WritingChat {...props} canApply chapterVersion={2} novelLifecycleId="n1" chapterLifecycleId="c1" onProposalAccepted={accepted} />);
    await waitFor(() => expect((screen.getByRole('button', { name: '采纳到本章' }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: '采纳到本章' }));
    await screen.findByText('已采纳');
    expect(accept).toHaveBeenCalledWith(1, 'p1', expect.objectContaining({ expected_version: 2, expected_content_hash: hash }), expect.any(AbortSignal));
    expect(accepted).toHaveBeenCalledWith(chapter);
    expect(props.onContentGenerated).not.toHaveBeenCalled();
  });

  it('同整数ID但章节生命周期改变时拒绝采纳', async () => {
    vi.mocked(api.listWritingTurns).mockResolvedValue([{ ...turn, proposal_id: 'p1', base_version: 2, novel_lifecycle_id: 'n1', chapter_lifecycle_id: '旧章' }]);
    vi.spyOn(writingProposalApi, 'get').mockResolvedValue({ id: 'p1', novel_id: 1, novel_lifecycle_id: 'n1', chapter_id: 2, chapter_lifecycle_id: '旧章', base_version: 2, base_content_hash: '', operation: 'append', status: 'pending' });
    const accept = vi.spyOn(writingProposalApi, 'accept');
    render(<WritingChat {...props} canApply chapterVersion={2} novelLifecycleId="n1" chapterLifecycleId="新章" />);
    await waitFor(() => expect((screen.getByRole('button', { name: '采纳到本章' }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: '采纳到本章' }));
    await screen.findByText('正文、版本或来源已变化，请先保存并重新生成候选');
    expect(accept).not.toHaveBeenCalled();
  });

  it('确认在途继续编辑时保留新草稿，不用服务端回包覆盖', async () => {
    const hash = await contentHash(props.currentContent);
    const proposal = { novel_id: 1, novel_lifecycle_id: 'n1', chapter_id: 2, chapter_lifecycle_id: 'c1', id: 'p1', status: 'pending' as const, operation: 'append' as const, base_version: 2, base_content_hash: hash };
    vi.mocked(api.listWritingTurns).mockResolvedValue([{ ...turn, base_content_hash: hash, proposal_id: 'p1', base_version: 2, novel_lifecycle_id: 'n1', chapter_lifecycle_id: 'c1' }]);
    vi.spyOn(writingProposalApi, 'get').mockResolvedValue(proposal);
    let finish!: (value: Awaited<ReturnType<typeof writingProposalApi.accept>>) => void;
    const accept = vi.spyOn(writingProposalApi, 'accept').mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    const accepted = vi.fn();
    const boundProps = { ...props, canApply: true, chapterVersion: 2, novelLifecycleId: 'n1', chapterLifecycleId: 'c1', onProposalAccepted: accepted };
    const { rerender } = render(<WritingChat {...boundProps} />);
    await waitFor(() => expect((screen.getByRole('button', { name: '采纳到本章' }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: '采纳到本章' }));
    await waitFor(() => expect(accept).toHaveBeenCalled());
    rerender(<WritingChat {...boundProps} currentContent="在途新草稿" canApply={false} />);
    finish({ proposal: { ...proposal, status: 'accepted' }, chapter: { id: 2, novel_id: 1, chapter_number: 1, title: '第一章', content: '服务端正文', word_count: 5, version: 3, created_at: '', updated_at: '' }, audit_id: 'a1' });
    await screen.findByText('候选已保存到服务器；编辑器中有后续修改，已保留，请核对版本后继续。');
    expect(accepted).not.toHaveBeenCalled();
  });
});

describe('动作卡片(对话即工作台)', () => {
  it('「+」菜单列出六种创作工具,选择后卡片进入对话流并可关闭', async () => {
    render(<WritingChat {...props} />);
    await screen.findByText(turn.assistant_text);
    fireEvent.click(screen.getByRole('button', { name: '添加创作工具' }));
    for (const label of ['编排任务', '高级续写', '选区改写', '一致性自查', '剧情走向', '资料检索']) {
      expect(screen.getByRole('menuitem', { name: new RegExp(label) })).toBeTruthy();
    }
    fireEvent.click(screen.getByRole('menuitem', { name: /编排任务/ }));
    expect(await screen.findByText('复合指令分解为检索、生成与检查')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '添加创作工具' }));
    fireEvent.click(screen.getByRole('menuitem', { name: /资料检索/ }));
    expect((await screen.findAllByText('搜索历史背景、专业知识...')).length).toBeGreaterThan(0);
    fireEvent.click(screen.getAllByRole('button', { name: '关闭卡片' })[0]);
    expect(screen.queryByText('复合指令分解为检索、生成与检查')).toBeNull();
    expect(screen.getAllByText('搜索历史背景、专业知识...').length).toBeGreaterThan(0);
  });

  it('卡片可折叠再展开,折叠后内容隐藏', async () => {
    render(<WritingChat {...props} />);
    await screen.findByText(turn.assistant_text);
    fireEvent.click(screen.getByRole('button', { name: '添加创作工具' }));
    fireEvent.click(screen.getByRole('menuitem', { name: /一致性自查/ }));
    const collapse = await screen.findByRole('button', { name: '折叠卡片' });
    fireEvent.click(collapse);
    expect(screen.getByRole('button', { name: '展开卡片' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '展开卡片' }));
    expect(screen.getByRole('button', { name: '折叠卡片' })).toBeTruthy();
  });
});

describe('输入体验(Claude Code 风格)', () => {
  it('Enter 直接发送,Shift+Enter 与输入法组合中的 Enter 不发送', async () => {
    const send = vi.spyOn(api, 'streamWritingTurn').mockImplementation(async (_id, data, callbacks) => {
      callbacks.onDone?.({ ...turn, id: 3, request_id: data.request_id, user_text: data.message, assistant_text: '好的。' });
    });
    render(<WritingChat {...props} />);
    await screen.findByText(turn.assistant_text);
    const input = screen.getByLabelText(/和 Nai 聊聊/);
    fireEvent.change(input, { target: { value: '测试一句' } });
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true });
    expect(send).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect(send).toHaveBeenCalledTimes(1));
  });
});
