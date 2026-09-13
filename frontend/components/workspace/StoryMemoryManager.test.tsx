import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { storyMemoryApi } from '@/lib/storyMemory';
import { chapterMemoryApi } from '@/lib/chapterMemory';
import { ApiError } from '@/lib/api';
import type { StoryMemorySnapshot } from '@/types/storyMemory';
import StoryMemoryManager from './StoryMemoryManager';
const props = { novelId: 1, novelLifecycleId: 'novel-one', chapterId: 3, chapterNumber: 3 };
const ref = { revision_id: 'rev-1', quote: '迟雁接过剑。', start: 0, content_hash: 'hash' };
const plan = { id: 'plan-1', parent_id: null, kind: 'scene' as const, plot_status: 'planned' as const, chapter_number: 4, title: '计划归还', conflict: '渡河', outcome: '剑归原主', origin: 'author' as const, source_refs: [], source_status: 'ready' as const };
const state = { id: 1, entity_id: 'sword', subject: '青纹剑', attribute: 'holder', value: '迟雁', value_entity_id: 'chiyan', chapter_established: 2, retired_chapter: null, status: 'active', source_status: 'ready' as const, origin: 'author' as const, source_refs: [ref] };
const candidate = { id: 'candidate-1', entity_id: 'sword', attribute: 'holder', value: '阿栩', value_entity_id: 'axu', effective_chapter: 3, source_refs: [ref], status: 'pending' as const, source_status: 'ready' as const, reason: '' };
const snapshot: StoryMemorySnapshot = { version: 5, novel_lifecycle_id: 'novel-one', entities: [{ id: 'sword', name: '青纹剑', kind: 'item' }, { id: 'chiyan', name: '迟雁', kind: 'character' }, { id: 'axu', name: '阿栩', kind: 'character' }], outline_nodes: [plan, { ...plan, id: 'actual-1', plot_status: 'occurred', title: '已经借剑', chapter_number: 1 }], states: [state], state_history: [{ ...state, id: 2, value: '阮舟', chapter_established: 1, retired_chapter: 2, status: 'retired' }, state], candidates: [candidate], warnings: [] };
beforeEach(() => { vi.spyOn(storyMemoryApi, 'get').mockResolvedValue(snapshot); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const ready = () => screen.findByText('计划归还');
const tab = (name: string) => fireEvent.click(screen.getByRole('tab', { name }));

describe('结构化记忆工作区', () => {
  it('计划与已发生大纲分区，新增计划携带版本和作品身份', async () => {
    const save = vi.spyOn(storyMemoryApi, 'saveOutline').mockResolvedValue(snapshot);
    render(<StoryMemoryManager {...props} />);
    await ready();
    expect(screen.getByText('作者计划')).toBeTruthy(); expect(screen.getByText('已发生剧情')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '新增大纲' }));
    fireEvent.change(screen.getByLabelText('大纲标题'), { target: { value: '进入旧塔' } });
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '新增大纲' }));
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(save).toHaveBeenCalledWith(1, null, expect.objectContaining({ expected_version: 5, novel_lifecycle_id: 'novel-one', request_id: expect.any(String), plot_status: 'planned', chapter_number: 3, title: '进入旧塔', source_refs: [] }), expect.any(AbortSignal));
  });

  it('按章读取状态并可查看持有者历史区间', async () => {
    render(<StoryMemoryManager {...props} />); await ready(); tab('人物与物品');
    expect(screen.getByText('截至第 3 章的状态')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('查看截至章节（留空看最新）'), { target: { value: '1' } });
    fireEvent.click(screen.getByRole('button', { name: '查看状态' }));
    await waitFor(() => expect(storyMemoryApi.get).toHaveBeenLastCalledWith(1, 1, expect.any(AbortSignal)));
    fireEvent.click(screen.getByRole('button', { name: '显示状态历史' }));
    expect(screen.getByText(/第 1 章生效 · 第 2 章起失效/)).toBeTruthy();
  });

  it('审阅候选须再次明确确认，失败保留候选与填写内容', async () => {
    const decide = vi.spyOn(storyMemoryApi, 'decide').mockRejectedValue(new Error('连接中断'));
    render(<StoryMemoryManager {...props} />); await ready(); tab('变化候选（1）');
    fireEvent.click(screen.getByRole('button', { name: '审阅并确认' }));
    expect(decide).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('审阅理由（可留空）'), { target: { value: '已核对转交动作' } });
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '确认候选' }));
    await screen.findByText('连接中断');
    expect(decide).toHaveBeenCalledWith(1, 'candidate-1', expect.objectContaining({ action: 'confirm', reason: '已核对转交动作', expected_version: 5 }), expect.any(AbortSignal));
    expect((screen.getByLabelText('审阅理由（可留空）') as HTMLTextAreaElement).value).toBe('已核对转交动作');
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '确认候选' }));
    await waitFor(() => expect(decide).toHaveBeenCalledTimes(2));
    expect(decide.mock.calls[1][2].request_id).toBe(decide.mock.calls[0][2].request_id);
  });

  it('失效来源禁确认但可拒绝，拒绝仍有审阅记录', async () => {
    vi.mocked(storyMemoryApi.get).mockResolvedValue({ ...snapshot, candidates: [{ ...candidate, source_status: 'needs_review' }] });
    const decide = vi.spyOn(storyMemoryApi, 'decide').mockResolvedValue({ ...snapshot, candidates: [{ ...candidate, status: 'rejected', reason: '原文已经修改' }] });
    render(<StoryMemoryManager {...props} />); await ready(); tab('变化候选（1）');
    expect((screen.getByRole('button', { name: '审阅并确认' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: '拒绝候选' }));
    fireEvent.change(screen.getByLabelText('审阅理由（可留空）'), { target: { value: '原文已经修改' } });
    vi.mocked(storyMemoryApi.get).mockResolvedValue({ ...snapshot, candidates: [{ ...candidate, status: 'rejected', reason: '原文已经修改' }] });
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '拒绝候选' }));
    await screen.findByText('已拒绝');
    expect(decide).toHaveBeenCalledWith(1, candidate.id, expect.objectContaining({ action: 'reject' }), expect.any(AbortSignal));
  });

  it('并发冲突刷新版本，表单内容保留供重新核对', async () => {
    const save = vi.spyOn(storyMemoryApi, 'createEntity').mockRejectedValueOnce(new ApiError('版本冲突', 409)).mockResolvedValue({ ...snapshot, version: 6 });
    render(<StoryMemoryManager {...props} />); await ready(); tab('人物与物品');
    fireEvent.click(screen.getByRole('button', { name: '新增人物或物品' }));
    fireEvent.change(screen.getByLabelText('实体名称'), { target: { value: '医师白榆' } });
    vi.mocked(storyMemoryApi.get).mockResolvedValue({ ...snapshot, version: 6 });
    const button = within(screen.getByRole('dialog')).getByRole('button', { name: '新增人物或物品' });
    fireEvent.click(button);
    await screen.findByText(/记忆已被其他操作更新/);
    expect((screen.getByLabelText('实体名称') as HTMLInputElement).value).toBe('医师白榆');
    fireEvent.click(button);
    await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    expect(save.mock.calls[1][1].expected_version).toBe(6);
  });

  it('切作品取消在途读取，旧书迟到数据不能出现', async () => {
    let complete!: (value: StoryMemorySnapshot) => void;
    vi.mocked(storyMemoryApi.get).mockImplementationOnce(() => new Promise((resolve) => { complete = resolve; })).mockResolvedValueOnce({ ...snapshot, novel_lifecycle_id: 'novel-two', outline_nodes: [{ ...plan, title: '第二本计划' }] });
    const { rerender } = render(<StoryMemoryManager {...props} />);
    const signal = vi.mocked(storyMemoryApi.get).mock.calls[0][2]!;
    rerender(<StoryMemoryManager {...props} novelId={2} novelLifecycleId="novel-two" />);
    await screen.findByText('第二本计划');
    await act(async () => complete(snapshot));
    expect(signal.aborted).toBe(true);
    expect(screen.queryByText('计划归还')).toBeNull();
  });

  it('切作品取消在途写入，迟到结果不关闭新书界面或污染内容', async () => {
    let complete!: (value: StoryMemorySnapshot) => void;
    const save = vi.spyOn(storyMemoryApi, 'saveOutline').mockImplementation(() => new Promise((resolve) => { complete = resolve; }));
    const { rerender } = render(<StoryMemoryManager {...props} />); await ready();
    fireEvent.click(screen.getByRole('button', { name: '新增大纲' }));
    fireEvent.change(screen.getByLabelText('大纲标题'), { target: { value: '旧书未完成操作' } });
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '新增大纲' }));
    const signal = save.mock.calls[0][3]!;
    vi.mocked(storyMemoryApi.get).mockResolvedValue({ ...snapshot, novel_lifecycle_id: 'novel-two', outline_nodes: [{ ...plan, title: '第二本计划' }] });
    rerender(<StoryMemoryManager {...props} novelId={2} novelLifecycleId="novel-two" />);
    await screen.findByText('第二本计划');
    await act(async () => complete(snapshot));
    expect(signal.aborted).toBe(true);
    expect(screen.queryByText('计划归还')).toBeNull();
  });

  it('原文已删除时保留候选，来源查看失败不触发确认', async () => {
    vi.spyOn(chapterMemoryApi, 'getRevision').mockRejectedValue(new ApiError('来源原文已删除', 404));
    const decide = vi.spyOn(storyMemoryApi, 'decide');
    render(<StoryMemoryManager {...props} />); await ready(); tab('变化候选（1）');
    fireEvent.click(screen.getByRole('button', { name: '查看来源原文' }));
    await screen.findByText('来源原文已删除');
    expect(screen.getByText('阿栩')).toBeTruthy();
    expect(decide).not.toHaveBeenCalled();
  });

  it('作者手动记录物品零数量，不关联持有者也不伪造出处', async () => {
    const create = vi.spyOn(storyMemoryApi, 'createState').mockResolvedValue(snapshot);
    render(<StoryMemoryManager {...props} />); await ready(); tab('人物与物品');
    fireEvent.click(screen.getByRole('button', { name: '记录确认状态' }));
    fireEvent.mouseDown(screen.getByLabelText('物品属性'));
    fireEvent.click(screen.getByRole('option', { name: '数量' }));
    fireEvent.change(screen.getByLabelText('状态内容'), { target: { value: '0' } });
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '记录作者确认状态' }));
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(create.mock.calls[0][1]).toMatchObject({ entity_id: 'sword', attribute: 'quantity', value: '0', value_entity_id: null, effective_chapter: 3, source_refs: [] });
  });

  it('重新核对失效大纲须说明理由，可明确确认为独立手写设定', async () => {
    vi.mocked(storyMemoryApi.get).mockResolvedValue({ ...snapshot, outline_nodes: [{ ...plan, source_status: 'needs_review' }] });
    const resolve = vi.spyOn(storyMemoryApi, 'resolve').mockResolvedValue(snapshot);
    render(<StoryMemoryManager {...props} />); await ready();
    fireEvent.click(screen.getByRole('button', { name: '重新核对来源' }));
    const button = within(screen.getByRole('dialog')).getByRole('button', { name: '重新核对来源' });
    fireEvent.click(button);
    await screen.findByText('请说明重新核对的理由');
    expect(resolve).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('重新核对理由'), { target: { value: '作者确认此计划继续独立有效' } });
    fireEvent.click(button);
    await waitFor(() => expect(resolve).toHaveBeenCalledTimes(1));
    expect(resolve.mock.calls[0].slice(0, 4)).toEqual([1, 'outline', plan.id, expect.objectContaining({ source_refs: [], reason: '作者确认此计划继续独立有效' })]);
  });

  it('提取只在明确操作后调用模型入口并使用选定原文版本', async () => {
    const revision = { id: 'saved-revision', chapter_id: 3, version: 2, chapter_number: 3, title: '原文第三章', content: '迟雁把剑交给阿栩。', content_hash: 'hash', created_at: '' };
    vi.spyOn(chapterMemoryApi, 'listRevisions').mockResolvedValue([revision]);
    vi.spyOn(chapterMemoryApi, 'getRevision').mockResolvedValue(revision);
    const extract = vi.spyOn(storyMemoryApi, 'extract').mockResolvedValue(snapshot);
    render(<StoryMemoryManager {...props} />); await ready();
    fireEvent.click(screen.getByRole('button', { name: '从当前章提取候选' }));
    await screen.findByLabelText('来源原文（只读）');
    expect(extract).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '从原文提取候选' }));
    await waitFor(() => expect(extract).toHaveBeenCalledTimes(1));
    expect(extract.mock.calls[0][1]).toMatchObject({ source_revision_id: 'saved-revision', expected_version: 5, novel_lifecycle_id: 'novel-one' });
  });
  it('同名人物使用独立说明创建，不改名混为同一实体', async () => {
    const save = vi.spyOn(storyMemoryApi, 'createEntity').mockResolvedValue(snapshot);
    render(<StoryMemoryManager {...props} />); await ready(); tab('人物与物品');
    fireEvent.click(screen.getByRole('button', { name: '新增人物或物品' }));
    fireEvent.change(screen.getByLabelText('实体名称'), { target: { value: '白榆' } });
    fireEvent.change(screen.getByLabelText('实体说明（区分同名，可留空）'), { target: { value: '城门女医师' } });
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '新增人物或物品' }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][1]).toMatchObject({ name: '白榆', description: '城门女医师', kind: 'character' });
  });
  it('同名状态归属按作者选择的稳定实体ID保存', async () => {
    const sameNames = [{ id: 'healer', name: '白榆', description: '女医师', kind: 'character' as const }, { id: 'carpenter', name: '白榆', description: '木匠', kind: 'character' as const }];
    vi.mocked(storyMemoryApi.get).mockResolvedValue({ ...snapshot, entities: sameNames });
    const save = vi.spyOn(storyMemoryApi, 'createState').mockResolvedValue(snapshot);
    render(<StoryMemoryManager {...props} />); await ready(); tab('人物与物品');
    fireEvent.mouseDown(screen.getByLabelText('查看实体'));
    fireEvent.click(screen.getByRole('option', { name: '白榆（木匠） · 人物 · 2' }));
    fireEvent.click(screen.getByRole('button', { name: '记录确认状态' }));
    fireEvent.change(screen.getByLabelText('属性（如位置、身份）'), { target: { value: '位置' } });
    fireEvent.change(screen.getByLabelText('状态内容'), { target: { value: '城门' } });
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '记录作者确认状态' }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][1]).toMatchObject({ entity_id: 'carpenter', attribute: '位置', value: '城门' });
  });
  it('场景只能选择同章的章大纲作为上级', async () => {
    vi.mocked(storyMemoryApi.get).mockResolvedValue({ ...snapshot, outline_nodes: [plan,
      { ...plan, id: 'volume', kind: 'volume', chapter_number: null, title: '卷大纲' },
      { ...plan, id: 'chapter3', kind: 'chapter', chapter_number: 3, title: '同章大纲' },
      { ...plan, id: 'chapter4', kind: 'chapter', chapter_number: 4, title: '其他章大纲' },
    ] });
    render(<StoryMemoryManager {...props} />); await ready();
    fireEvent.click(screen.getByRole('button', { name: '新增大纲' }));
    fireEvent.mouseDown(screen.getByLabelText('上级大纲'));
    expect(screen.getByRole('option', { name: '同章大纲' })).toBeTruthy();
    expect(screen.queryByRole('option', { name: '卷大纲' })).toBeNull();
    expect(screen.queryByRole('option', { name: '其他章大纲' })).toBeNull();
  });
});
