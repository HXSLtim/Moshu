import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/lib/api';
import { charactersApi } from '@/lib/characters';
import type { CharacterAppearanceResponse, CharacterResponse, CharacterTimelineResponse } from '@/lib/api/generated/model';
import type { ChapterSummary, ChapterSummaryPage } from '@/types';
import CharacterTimeline from './CharacterTimeline';

const roster: CharacterResponse[] = [
  { id: 5, novel_id: 1, name: '林昭', created_at: '2026-10-02T00:00:00', updated_at: '2026-10-02T00:00:00' },
  { id: 6, novel_id: 1, name: '沈孤鸿', created_at: '2026-10-02T00:00:00', updated_at: '2026-10-02T00:00:00' },
];
const appearance = (id: number, chapter: number, type: string, description: string): CharacterAppearanceResponse => ({
  id,
  chapter_id: chapter * 100,
  chapter_number: chapter,
  character_id: 5,
  character_name: '林昭',
  created_at: '2026-10-02T00:00:00',
  appearance_type: type,
  description,
});
const timelineOf = (appearances: CharacterAppearanceResponse[]): CharacterTimelineResponse => ({
  appearances, character_id: 5, character_name: '林昭',
});

beforeEach(() => {
  vi.spyOn(charactersApi, 'list').mockResolvedValue(roster);
  vi.spyOn(charactersApi, 'timeline').mockResolvedValue(timelineOf([
    appearance(2, 3, 'mentioned', '有人在茶馆提起林昭。'),
    appearance(1, 1, 'main', '林昭夜探黑市。'),
  ]));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('TA 的经历区', () => {
  it('自动选第一位人物，乱序出场按章节号升序排线', async () => {
    render(<CharacterTimeline novelId={1} />);
    await screen.findByText('林昭 的出场排线');
    const chapters = await screen.findAllByText(/第 \d+ 章/);
    expect(chapters[0].textContent).toBe('第 1 章');
    expect(chapters[1].textContent).toBe('第 3 章');
    expect(screen.getByText('主场')).toBeTruthy();
    expect(screen.getByText('提及')).toBeTruthy();
  });

  it('无人物诚实空态并指向人物档案区', async () => {
    vi.mocked(charactersApi.list).mockResolvedValue([]);
    render(<CharacterTimeline novelId={1} />);
    await screen.findByText('还没有人物档案。');
    expect(screen.queryByLabelText('人物')).toBeNull();
  });

  it('无出场诚实空态，头部与空态都有补录入口', async () => {
    vi.mocked(charactersApi.timeline).mockResolvedValue(timelineOf([]));
    render(<CharacterTimeline novelId={1} />);
    await screen.findByText('还没有出场记录。');
    expect(screen.getAllByRole('button', { name: '补录出场' })).toHaveLength(2);
  });

  it('补录出场：章节选择映射 chapter_id，保存后刷新时间线', async () => {
    vi.mocked(charactersApi.timeline).mockResolvedValue(timelineOf([]));
    const chapters: ChapterSummary[] = [
      { id: 77, novel_id: 1, chapter_number: 2, title: '夜行', word_count: 1200, version: 1, created_at: '2026-10-02T00:00:00' },
    ];
    const page: ChapterSummaryPage = { items: chapters, total: 1, page: 1, page_size: 50, has_more: false };
    vi.spyOn(api, 'getChapterSummaries').mockResolvedValue(page);
    const createAppearance = vi.spyOn(charactersApi, 'createAppearance').mockResolvedValue(appearance(9, 2, 'supporting', 'x'));
    render(<CharacterTimeline novelId={1} />);
    await screen.findByText('还没有出场记录。');
    fireEvent.click(screen.getAllByRole('button', { name: '补录出场' })[0]);
    await screen.findByRole('dialog');
    // MUI Select 禁用态标 aria-disabled="true"，章节列表加载完成后属性移除。
    await waitFor(() => expect(screen.getByLabelText('章节').getAttribute('aria-disabled')).toBeNull());
    fireEvent.mouseDown(screen.getByLabelText('章节'));
    fireEvent.click(await screen.findByRole('option', { name: '第 2 章 夜行' }));
    fireEvent.click(screen.getByRole('button', { name: '补录' }));
    await waitFor(() => expect(createAppearance).toHaveBeenCalledWith({
      character_id: 5, chapter_id: 77, appearance_type: 'supporting', description: null,
    }));
    await waitFor(() => expect(charactersApi.timeline).toHaveBeenCalledTimes(2));
  });

  it('经历读取失败诚实展示并可重试', async () => {
    vi.mocked(charactersApi.timeline)
      .mockRejectedValueOnce(new Error('服务器开小差了'))
      .mockResolvedValue(timelineOf([appearance(1, 1, 'main', '林昭夜探黑市。')]));
    render(<CharacterTimeline novelId={1} />);
    await screen.findByText('服务器开小差了');
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    expect(await screen.findByText('第 1 章')).toBeTruthy();
  });
});
