import React from 'react';
import { webcrypto } from 'node:crypto';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '@/lib/api';
import { contentHash } from '@/lib/writingChat';
import { writingProposalApi } from '@/lib/writingProposal';
import { chapterMemoryApi } from '@/lib/chapterMemory';
import type { ContextManifest } from '@/types/context';
import type { AgentAction, WritingTurn } from '@/types/writingChat';
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
  it('「让 AI 起草下一章」入口只预填输入框，不自动发送', async () => {
    const send = vi.spyOn(api, 'streamWritingTurn');
    render(<WritingChat {...props} entryIntent="next-chapter" />);
    await screen.findByText(turn.assistant_text);
    expect((screen.getByLabelText('和 Nai 聊聊') as HTMLTextAreaElement).value).toBe('帮我起草下一章。');
    expect(send).not.toHaveBeenCalled();
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
    expect(screen.getByPlaceholderText(/Enter 发送/)).toBeTruthy();
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

  it('同整数ID但章节生命周期改变时交服务端裁决，展示服务端拒绝原因', async () => {
    const hash = await contentHash(props.currentContent);
    vi.mocked(api.listWritingTurns).mockResolvedValue([{ ...turn, proposal_id: 'p1', base_version: 2, novel_lifecycle_id: 'n1', chapter_lifecycle_id: '旧章' }]);
    vi.spyOn(writingProposalApi, 'get').mockResolvedValue({ id: 'p1', novel_id: 1, novel_lifecycle_id: 'n1', chapter_id: 2, chapter_lifecycle_id: '旧章', base_version: 2, base_content_hash: hash, operation: 'append', status: 'pending' });
    const serverReason = '这稿是按当时的章节情况准备的，现在书里的章节有了变化。要不要按最新的章节重新生成一稿？';
    const accept = vi.spyOn(writingProposalApi, 'accept').mockRejectedValue(new ApiError(serverReason, 409));
    render(<WritingChat {...props} canApply chapterVersion={2} novelLifecycleId="n1" chapterLifecycleId="新章" />);
    await waitFor(() => expect((screen.getByRole('button', { name: '采纳到本章' }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: '采纳到本章' }));
    await screen.findByText(serverReason);
    expect(accept).toHaveBeenCalledWith(1, 'p1', expect.objectContaining({ expected_version: 2, expected_content_hash: hash }), expect.any(AbortSignal));
  });

  it('正文与候选基础不一致时提示先保存，不发采纳请求', async () => {
    vi.mocked(api.listWritingTurns).mockResolvedValue([{ ...turn, proposal_id: 'p1', base_version: 2, novel_lifecycle_id: 'n1', chapter_lifecycle_id: 'c1' }]);
    vi.spyOn(writingProposalApi, 'get').mockResolvedValue({ id: 'p1', novel_id: 1, novel_lifecycle_id: 'n1', chapter_id: 2, chapter_lifecycle_id: 'c1', base_version: 2, base_content_hash: '过期的哈希', operation: 'append', status: 'pending' });
    const accept = vi.spyOn(writingProposalApi, 'accept');
    render(<WritingChat {...props} canApply chapterVersion={2} novelLifecycleId="n1" chapterLifecycleId="c1" />);
    await waitFor(() => expect((screen.getByRole('button', { name: '采纳到本章' }) as HTMLButtonElement).disabled).toBe(false));
    expect(screen.queryByText(/将写入：/)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '采纳到本章' }));
    await screen.findByText('正文已经改动，和这条候选对不上了——请先保存修改，再让 AI 重新生成一稿');
    expect(accept).not.toHaveBeenCalled();
  });

  it('候选卡在确认前显示服务端落点说明', async () => {
    const hash = await contentHash(props.currentContent);
    vi.mocked(api.listWritingTurns).mockResolvedValue([{ ...turn, proposal_id: 'p1', base_version: 2, novel_lifecycle_id: 'n1', chapter_lifecycle_id: 'c1', result: { reply: '', actions: [], uncertainties: [], landing: '第 2 章的新章' } }]);
    vi.spyOn(writingProposalApi, 'get').mockResolvedValue({ id: 'p1', novel_id: 1, novel_lifecycle_id: 'n1', chapter_id: 2, chapter_lifecycle_id: 'c1', base_version: 2, base_content_hash: hash, operation: 'append', status: 'pending' });
    render(<WritingChat {...props} canApply chapterVersion={2} novelLifecycleId="n1" chapterLifecycleId="c1" />);
    await screen.findByText('将写入：第 2 章的新章');
    expect(screen.getByRole('button', { name: '采纳到本章' })).toBeTruthy();
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


describe('设定提案决策', () => {
  const settingsActions: AgentAction[] = [
    { kind: 'fact', subject: '林昭', attribute: '随身物品', value: '刻纹玉佩' },
    { kind: 'entity', name: '守门人', entity_kind: 'character', description: '城门老卒，认得玉佩纹路' },
  ];
  const settingsTurn: WritingTurn = { ...turn, id: 9, result: { reply: '', actions: settingsActions, uncertainties: [] } };
  const decidedAt = '2026-10-02T12:00:00';
  const settingsProps = { ...props, onSettingsApplied: vi.fn() };
  const renderSettings = () => { vi.mocked(api.listWritingTurns).mockResolvedValue([settingsTurn]); };

  it('历史轮已写入的设定卡刷新后仍显示已写入，不复活成待确认', async () => {
    vi.mocked(api.listWritingTurns).mockResolvedValue([{ ...settingsTurn, result: { reply: '', actions: settingsActions.map((action) => ({ ...action, decision: 'applied' as const, decided_at: decidedAt })), uncertainties: [] } }]);
    render(<WritingChat {...settingsProps} />);
    await screen.findByText(/已写入设定/);
    expect(screen.queryByRole('button', { name: '确认写入设定' })).toBeNull();
    expect(settingsProps.onSettingsApplied).not.toHaveBeenCalled();
  });

  it('旧轮没有 decision 字段时兼容为待确认，确认后一次调用服务端决策端点', async () => {
    renderSettings();
    const decide = vi.spyOn(api, 'decideTurnActions').mockResolvedValue({
      ...settingsTurn, result: { reply: '', actions: settingsActions.map((action) => ({ ...action, decision: 'applied' as const, decided_at: decidedAt })), uncertainties: [] },
    });
    render(<WritingChat {...settingsProps} />);
    fireEvent.click(await screen.findByRole('button', { name: '确认写入设定' }));
    await screen.findByText(/已写入设定/);
    expect(decide).toHaveBeenCalledWith(1, 9, 'applied');
    expect(settingsProps.onSettingsApplied).toHaveBeenCalledTimes(1);
  });

  it('「先不写入」也走决策端点落 skipped，终态可见', async () => {
    renderSettings();
    const decide = vi.spyOn(api, 'decideTurnActions').mockResolvedValue({
      ...settingsTurn, result: { reply: '', actions: settingsActions.map((action) => ({ ...action, decision: 'skipped' as const, decided_at: decidedAt })), uncertainties: [] },
    });
    render(<WritingChat {...settingsProps} />);
    fireEvent.click(await screen.findByRole('button', { name: '先不写入' }));
    await screen.findByText(/已按你的选择跳过/);
    expect(decide).toHaveBeenCalledWith(1, 9, 'skipped');
    expect(settingsProps.onSettingsApplied).not.toHaveBeenCalled();
  });

  it('服务端拒绝（已写入不可改口）时展示拒绝原因，卡片保持可重试', async () => {
    renderSettings();
    const serverReason = '这条设定已经写入，不能改为跳过；如需撤销请在项目与设定里手动修改。';
    vi.spyOn(api, 'decideTurnActions').mockRejectedValue(new ApiError(serverReason, 409));
    render(<WritingChat {...settingsProps} />);
    fireEvent.click(await screen.findByRole('button', { name: '先不写入' }));
    await screen.findByText(serverReason);
    expect(screen.getByRole('button', { name: '确认写入设定' })).toBeTruthy();
  });

  it('状态 Chip 不嵌进 Typography（div 不得嵌 p，否则 hydration 报错）', async () => {
    // 部分已决策（待确认卡带单条 Chip）与全决策混合（终态列表带 Chip）两条渲染路径都验证。
    vi.mocked(api.listWritingTurns).mockResolvedValue([
      { ...settingsTurn, result: { reply: '', actions: [{ ...settingsActions[0], decision: 'applied' as const, decided_at: decidedAt }, settingsActions[1]], uncertainties: [] } },
      { ...settingsTurn, id: 10, request_id: 'saved-turn-2', result: { reply: '', actions: [{ ...settingsActions[0], decision: 'applied' as const, decided_at: decidedAt }, { ...settingsActions[1], decision: 'skipped' as const, decided_at: decidedAt }], uncertainties: [] } },
    ]);
    const { container } = render(<WritingChat {...settingsProps} />);
    await screen.findByText(/已处理：写入 1 项/);
    expect(container.querySelector('p .MuiChip-root')).toBeNull();
    // 批1 后审核模式改为 ToggleButtonGroup（不再产生 Chip），状态章仅两条渲染路径各 1+2。
    expect(container.querySelectorAll('.MuiChip-root').length).toBe(3);
  });
});


describe('输入体验(Claude Code 风格)', () => {  it('Enter 直接发送,Shift+Enter 与输入法组合中的 Enter 不发送', async () => {
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


describe('对话框唯一形态(能力工具化)', () => {
  it('工具事件渲染为内联块,能力工具两阶段状态可见', async () => {
    const send = vi.spyOn(api, 'streamWritingTurn').mockImplementation(async (_id, data, callbacks) => {
      callbacks.onTool?.('search_story_bible', { summary: '查到青霜剑' });
      callbacks.onTool?.('orchestrate', { status: 'running', summary: '' });
      await new Promise((resolve) => setTimeout(resolve, 300));
      callbacks.onDone?.({ ...turn, id: 4, request_id: data.request_id, user_text: data.message, assistant_text: '已完成编排。' });
    });
    render(<WritingChat {...props} />);
    await screen.findByText(turn.assistant_text);
    fireEvent.change(screen.getByLabelText(/和 Nai 聊聊/), { target: { value: '先查再写' } });
    fireEvent.keyDown(screen.getByLabelText(/和 Nai 聊聊/), { key: 'Enter' });
    expect(await screen.findByText('已检索设定账本')).toBeTruthy();
    expect(screen.getByText('正在编排任务编排…')).toBeTruthy();
    expect(send).toHaveBeenCalledTimes(1);
  });

  it('处理中 Enter 入队,完成后自动发送排队消息', async () => {
    const releaseRef: { current: ((turn: WritingTurn) => void) | null } = { current: null };
    const gate = new Promise<WritingTurn>((resolve) => { releaseRef.current = resolve; });
    const send = vi.spyOn(api, 'streamWritingTurn').mockImplementation(async (_id, data, callbacks) => {
      if (data.message === '第二条') {
        callbacks.onDone?.({ ...turn, id: 5, request_id: data.request_id, user_text: '第二条', assistant_text: '排队成功' });
        return;
      }
      const settled = await gate;
      callbacks.onDone?.({ ...settled, request_id: data.request_id });
    });
    render(<WritingChat {...props} />);
    await screen.findByText(turn.assistant_text);
    fireEvent.change(screen.getByLabelText(/和 Nai 聊聊/), { target: { value: '第一条' } });
    fireEvent.keyDown(screen.getByLabelText(/和 Nai 聊聊/), { key: 'Enter' });
    const input = screen.getByLabelText(/排队下一条消息/);
    fireEvent.change(input, { target: { value: '第二条' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(screen.getByText(/已排队：第二条/)).toBeTruthy();
    releaseRef.current?.({ ...turn, id: 4, request_id: 'first', user_text: '第一条', assistant_text: '完成一' });
    await waitFor(() => expect(send).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('排队成功')).toBeTruthy();
  });

  it('流式增量立即上屏，操作行等完成才出现', async () => {
    let release: (() => void) | undefined;
    vi.spyOn(api, 'streamWritingTurn').mockImplementation((_id, data, callbacks) => new Promise((resolve) => {
      callbacks.onChunk?.('第一段就上屏。');
      callbacks.onChunk?.('第二段继续。');
      release = () => {
        callbacks.onDone?.({ ...turn, id: 2, request_id: data.request_id, user_text: data.message, assistant_text: '第一段就上屏。第二段继续。' });
        resolve();
      };
    }));
    render(<WritingChat {...props} />);
    await screen.findByText(turn.assistant_text);
    fireEvent.change(screen.getByLabelText('和 Nai 聊聊'), { target: { value: '继续写' } });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    expect(await screen.findByText('第一段就上屏。第二段继续。')).toBeTruthy();
    expect(screen.getByText('正在继续写…')).toBeTruthy();
    // 历史完成轮自带一颗复制钮；流式轮的操作行要等完成才出现（此时全场仅 1 颗）。
    expect(screen.getAllByRole('button', { name: '复制回复' })).toHaveLength(1);
    release?.();
    await waitFor(() => expect(screen.getAllByRole('button', { name: '复制回复' })).toHaveLength(2));
    expect(screen.queryByText('正在继续写…')).toBeNull();
  });
});
