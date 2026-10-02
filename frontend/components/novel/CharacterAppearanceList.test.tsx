import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { CharacterAppearanceResponse } from '@/lib/api/generated/model';
import CharacterAppearanceList from './CharacterAppearanceList';

const appearance = (id: number, chapter: number, type?: string, description?: string): CharacterAppearanceResponse => ({
  id,
  chapter_id: chapter * 100,
  chapter_number: chapter,
  character_id: 5,
  character_name: '林昭',
  created_at: '2026-10-02T00:00:00',
  appearance_type: type,
  description,
});

afterEach(cleanup);

describe('出场条目列表', () => {
  it('乱序输入按章节号升序排线', () => {
    render(<CharacterAppearanceList appearances={[
      appearance(2, 3, 'mentioned', '有人在茶馆提起林昭。'),
      appearance(1, 1, 'main', '林昭夜探黑市。'),
    ]} />);
    const chapters = screen.getAllByText(/第 \d+ 章/);
    expect(chapters).toHaveLength(2);
    expect(chapters[0].textContent).toBe('第 1 章');
    expect(chapters[1].textContent).toBe('第 3 章');
  });

  it('出场类型映射作者词汇，未知类型原样透传', () => {
    render(<CharacterAppearanceList appearances={[
      appearance(1, 1, 'main'), appearance(2, 2, 'supporting'), appearance(3, 3, '客串'),
    ]} />);
    expect(screen.getByText('主场')).toBeTruthy();
    expect(screen.getByText('出场')).toBeTruthy();
    expect(screen.getByText('客串')).toBeTruthy();
  });

  it('无说明不出空描述行', () => {
    const { container } = render(<CharacterAppearanceList appearances={[appearance(1, 1, 'main')]} />);
    expect(screen.getByText('第 1 章')).toBeTruthy();
    expect(container.textContent).not.toContain('undefined');
  });
});
