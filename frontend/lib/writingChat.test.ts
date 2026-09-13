import { webcrypto } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { appendWritingCandidate, contentHash, mergeWritingTurns } from './writingChat';
import type { WritingTurn } from '@/types/writingChat';

export const sampleTurn: WritingTurn = { id: 1, request_id: 'request-one', novel_id: 1, chapter_id: 2, chapter_title: '第一章', mode: 'continue', user_text: '接着写', assistant_text: '新的候选', base_content_hash: '', status: 'completed', error: null, created_at: '2026-09-08T00:00:00' };
beforeEach(() => vi.stubGlobal('crypto', webcrypto));
afterEach(() => vi.unstubAllGlobals());
describe('持久创作对话', () => {
  it('轮询不能覆盖完成态，重复记录合并且旧记录按顺序补入', () => {
    const merged = mergeWritingTurns([sampleTurn], [{ ...sampleTurn, status: 'pending', assistant_text: '' }, { ...sampleTurn, id: 2, request_id: 'two' }]);
    expect(merged).toHaveLength(2);
    expect(merged[0].assistant_text).toBe('新的候选');
  });
  it('只允许在原小说原章节的正文快照上追加候选', async () => {
    const turn = { ...sampleTurn, base_content_hash: await contentHash('正文') };
    expect(await appendWritingCandidate('正文', 1, 2, turn)).toBe('正文\n\n新的候选');
    await expect(appendWritingCandidate('正文', 1, 3, turn)).rejects.toThrow('所属的章节');
    await expect(appendWritingCandidate('新正文', 1, 2, turn)).rejects.toThrow('正文已修改');
  });
  it('讨论回复不能当作续写自动采纳', async () => {
    await expect(appendWritingCandidate('', 1, 2, { ...sampleTurn, mode: 'discuss' })).rejects.toThrow('不是可采纳');
  });
});
