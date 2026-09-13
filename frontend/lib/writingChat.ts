import type { WritingTurn } from '@/types/writingChat';

/** 轮询的旧状态不能覆盖已经完成的回复。 */
export function mergeWritingTurns(current: WritingTurn[], incoming: WritingTurn[]): WritingTurn[] {
  const entries = new Map(current.map((turn) => [turn.request_id, turn]));
  for (const turn of incoming) {
    const previous = entries.get(turn.request_id);
    if (previous && previous.status !== 'pending' && turn.status === 'pending') continue;
    entries.set(turn.request_id, turn);
  }
  return [...entries.values()].sort((a, b) => (a.id || a.local_order || Number.MAX_SAFE_INTEGER) - (b.id || b.local_order || Number.MAX_SAFE_INTEGER));
}

export async function contentHash(content: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(content));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

export async function appendWritingCandidate(content: string, novelId: number, chapterId: number | null, turn: WritingTurn): Promise<string> {
  if (turn.novel_id !== novelId || turn.chapter_id !== chapterId) throw new Error('请先打开这条回复所属的章节');
  if (turn.status !== 'completed' || turn.mode !== 'continue' || !turn.assistant_text.trim()) throw new Error('这条回复不是可采纳的续写候选');
  if (await contentHash(content) !== turn.base_content_hash) throw new Error('正文已修改，请重新生成续写，或复制需要的部分手动编辑');
  return content + (content && !content.endsWith('\n') ? '\n\n' : '') + turn.assistant_text;
}
