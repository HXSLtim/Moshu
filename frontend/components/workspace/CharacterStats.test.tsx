import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { charactersApi } from '@/lib/characters';
import CharacterStats from './CharacterStats';
import type { CharacterResponse } from '@/lib/api/generated/model';
import type { Novel } from '@/types';

const novel: Novel = {
  id: 7,
  title: '墨色长河',
  user_id: 1,
  created_at: '2026-10-02T00:00:00',
  worldview: '【主要角色】\n张三：主角，年轻的剑客\n李四：反派，邪恶的法师\n\n【章节大纲】\n第一章：茶馆相遇',
};
const archives: CharacterResponse[] = [
  { id: 1, novel_id: 7, name: '张三', created_at: '2026-10-02T00:00:00', updated_at: '2026-10-02T00:00:00' },
  { id: 2, novel_id: 7, name: '王五', created_at: '2026-10-02T00:00:00', updated_at: '2026-10-02T00:00:00' },
];
const props = { novel, currentContent: '张三走进茶馆。张三坐下。王五跟了进来。', previousContent: '' };

beforeEach(() => {
  window.localStorage.clear();
  vi.spyOn(charactersApi, 'list').mockResolvedValue(archives);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); window.localStorage.clear(); });

describe('角色统计数据源切换', () => {
  it('默认维持世界观正则源，旧书零回退', async () => {
    render(<CharacterStats {...props} />);
    await screen.findByText('张三');
    expect(screen.queryByText('王五')).toBeNull();
    expect(window.localStorage.getItem('nai.character-stats.source.7')).toBeNull();
  });

  it('有档案时给一次性引导，点「切换」按档案名单计数并记住偏好', async () => {
    render(<CharacterStats {...props} />);
    await screen.findByText('已建档 2 名人物。');
    fireEvent.click(screen.getByRole('button', { name: '切换' }));
    expect(await screen.findByText('王五')).toBeTruthy();
    expect(window.localStorage.getItem('nai.character-stats.source.7')).toBe('character');
  });

  it('引导点「知道了」后按书记忆，重渲染不再出现', async () => {
    render(<CharacterStats {...props} />);
    await screen.findByText('已建档 2 名人物。');
    fireEvent.click(screen.getByRole('button', { name: '知道了' }));
    await waitFor(() => expect(screen.queryByText('已建档 2 名人物。')).toBeNull());
    expect(window.localStorage.getItem('nai.character-stats.source-hint-dismissed.7')).toBe('1');
    cleanup();
    render(<CharacterStats {...props} />);
    await screen.findByText('张三');
    expect(screen.queryByText('已建档 2 名人物。')).toBeNull();
  });

  it('档案源零档案诚实空态，指向设定账本', async () => {
    vi.mocked(charactersApi.list).mockResolvedValue([]);
    window.localStorage.setItem('nai.character-stats.source.7', 'character');
    render(<CharacterStats {...props} />);
    await screen.findByText('还没有人物档案。');
  });

  it('无【主要角色】的旧书：正则源给格式引导，切档案源即救济', async () => {
    render(<CharacterStats {...props} novel={{ ...novel, worldview: '本书没有角色小节。' }} />);
    await screen.findByText('还没有从世界观找到角色名单。');
    fireEvent.click(screen.getByRole('button', { name: '人物档案' }));
    expect(await screen.findByText('张三')).toBeTruthy();
  });

  it('预存档案源偏好时渲染即按档案名单计数', async () => {
    window.localStorage.setItem('nai.character-stats.source.7', 'character');
    render(<CharacterStats {...props} />);
    expect(await screen.findByText('王五')).toBeTruthy();
  });
});
