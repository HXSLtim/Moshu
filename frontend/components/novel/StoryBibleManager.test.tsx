import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/lib/api';
import type { StoryFact } from '@/types/storyBible';
import StoryBibleManager from './StoryBibleManager';

function fact(id: number): StoryFact {
  return { id, novel_id: 7, subject: `人物${id}`, attribute: '身份', value: '旅人', description: null, chapter_established: null,
    retired_chapter: null, status: 'active', created_at: '', updated_at: null };
}
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
beforeEach(() => {
  vi.spyOn(api, 'listStoryFacts').mockResolvedValue([]);
  vi.spyOn(api, 'listStoryEvents').mockResolvedValue([]);
});

describe('设定账本作者操作', () => {
  it('创建失败保留表单，重试成功后展示已保存事实', async () => {
    const created = { ...fact(1), subject: '林夏' };
    const create = vi.spyOn(api, 'createStoryFact').mockRejectedValueOnce(new Error('网络中断')).mockResolvedValue(created);
    render(<StoryBibleManager novelId={7} />);
    await screen.findByText('还没有设定事实，可以先添加一条。');
    fireEvent.click(screen.getByRole('button', { name: '新增设定事实' }));
    fireEvent.change(screen.getByLabelText('主体（人物、地点或组织）'), { target: { value: '林夏' } });
    fireEvent.change(screen.getByLabelText('属性（如身份、位置）'), { target: { value: '身份' } });
    fireEvent.change(screen.getByLabelText('事实内容'), { target: { value: '旅人' } });
    fireEvent.click(screen.getByRole('button', { name: '保存设定' }));
    await screen.findByText('网络中断');
    expect((screen.getByLabelText('事实内容') as HTMLInputElement).value).toBe('旅人');
    vi.mocked(api.listStoryFacts).mockResolvedValue([created]);
    fireEvent.click(screen.getByRole('button', { name: '保存设定' }));
    await screen.findByText('林夏 · 身份');
    expect(create).toHaveBeenLastCalledWith(expect.objectContaining({ novel_id: 7, subject: '林夏', attribute: '身份', value: '旅人' }));
  });
  it('超过一页的设定可以继续加载', async () => {
    vi.mocked(api.listStoryFacts).mockResolvedValueOnce(Array.from({ length: 20 }, (_, index) => fact(index + 1))).mockResolvedValueOnce([fact(21)]);
    render(<StoryBibleManager novelId={7} />);
    fireEvent.click(await screen.findByRole('button', { name: '加载更多设定事实' }));
    await screen.findByText('人物21 · 身份');
    expect(api.listStoryFacts).toHaveBeenLastCalledWith(7, 20, 20, expect.anything());
    expect(screen.queryByRole('button', { name: '加载更多设定事实' })).toBeNull();
  });
  it('删除需要确认，成功后从列表移除', async () => {
    vi.mocked(api.listStoryFacts).mockResolvedValueOnce([fact(1)]).mockResolvedValue([]);
    const remove = vi.spyOn(api, 'deleteStoryFact').mockResolvedValue(undefined);
    render(<StoryBibleManager novelId={7} />);
    fireEvent.click(await screen.findByRole('button', { name: '删除人物1' }));
    expect(remove).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '确认删除' }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith(1));
    await screen.findByText('还没有设定事实，可以先添加一条。');
  });
  it('剧情事件可以记录参与角色与伏笔', async () => {
    const create = vi.spyOn(api, 'createStoryEvent').mockResolvedValue({ id: 1, novel_id: 7, title: '初入城', description: '主角遇见守将', story_day: 2, chapter: 1, involved_characters: ['林夏', '守将'], foreshadowing: '玉佩', status: 'planned', created_at: '', updated_at: null });
    render(<StoryBibleManager novelId={7} />);
    fireEvent.click(screen.getByRole('tab', { name: '剧情与伏笔' }));
    await screen.findByText('还没有剧情事件，可以先添加一条。');
    fireEvent.click(screen.getByRole('button', { name: '新增剧情事件' }));
    for (const [label, value] of [['事件标题', '初入城'], ['事件描述', '主角遇见守将'], ['故事第几天', '2'], ['对应章节（可留空）', '1'], ['关联角色（用顿号分隔）', '林夏、守将'], ['伏笔或线索', '玉佩']]) {
      fireEvent.change(screen.getByLabelText(label), { target: { value } });
    }
    fireEvent.click(screen.getByRole('button', { name: '保存设定' }));
    await waitFor(() => expect(create).toHaveBeenCalledWith(expect.objectContaining({ novel_id: 7, involved_characters: ['林夏', '守将'], chapter: 1, story_day: 2, foreshadowing: '玉佩' })));
  });
});
