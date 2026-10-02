import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { charactersApi } from '@/lib/characters';
import type { CharacterResponse } from '@/lib/api/generated/model';
import CharacterManager from './CharacterManager';

const person: CharacterResponse = {
  id: 5, novel_id: 1, name: '林昭', occupation: '游侠', importance_level: 'main',
  created_at: '2026-10-02T00:00:00', updated_at: '2026-10-02T00:00:00',
};
const props = { novelId: 1 };
beforeEach(() => { vi.spyOn(charactersApi, 'list').mockResolvedValue([person]); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('人物档案管理区（样板）', () => {
  it('按管理密度档渲染档案列表：名字、身份、重要程度章与删除入口', async () => {
    render(<CharacterManager {...props} />);
    await screen.findByText('林昭');
    expect(screen.getByText('游侠')).toBeTruthy();
    expect(screen.getByText('主力')).toBeTruthy();
    expect(screen.getByRole('button', { name: '删除林昭' })).toBeTruthy();
  });

  it('空书诚实显示空态，不造占位数据', async () => {
    vi.mocked(charactersApi.list).mockResolvedValue([]);
    render(<CharacterManager {...props} />);
    await screen.findByText('还没有人物档案。');
    expect(screen.queryByRole('button', { name: /删除/ })).toBeNull();
  });

  it('读取失败展示原因并可重试', async () => {
    vi.mocked(charactersApi.list).mockRejectedValue(new Error('服务器开小差了'));
    render(<CharacterManager {...props} />);
    await screen.findByText('服务器开小差了');
    vi.mocked(charactersApi.list).mockResolvedValue([person]);
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    expect(await screen.findByText('林昭')).toBeTruthy();
  });

  it('删除前必须经确认对话框，确认后调用删除并刷新列表', async () => {
    const remove = vi.spyOn(charactersApi, 'remove').mockResolvedValue(undefined);
    render(<CharacterManager {...props} />);
    await screen.findByText('林昭');
    fireEvent.click(screen.getByRole('button', { name: '删除林昭' }));
    const dialog = await screen.findByRole('dialog');
    expect(dialog.textContent).toContain('确定删除「林昭」？');
    fireEvent.click(screen.getByRole('button', { name: '确认删除' }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith(5));
    await waitFor(() => expect(charactersApi.list).toHaveBeenCalledTimes(2));
  });

  it('取消删除不发出请求', async () => {
    const remove = vi.spyOn(charactersApi, 'remove').mockResolvedValue(undefined);
    render(<CharacterManager {...props} />);
    fireEvent.click(await screen.findByRole('button', { name: '删除林昭' }));
    fireEvent.click(await screen.findByRole('button', { name: '取消' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(remove).not.toHaveBeenCalled();
  });
});
