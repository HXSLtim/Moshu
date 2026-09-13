/** 候选稿始终绑定生成时的章节和正文快照，避免旧选区覆盖新稿。 */
export interface RewriteSnapshot {
  novelId: number;
  chapterId: number;
  content: string;
  start: number;
  end: number;
  originalText: string;
}

export function applyRewrite(
  content: string,
  novelId: number,
  chapterId: number | null,
  snapshot: RewriteSnapshot,
  replacement: string,
): string {
  if (novelId !== snapshot.novelId || chapterId !== snapshot.chapterId) {
    throw new Error('当前章节已切换，请在原章节重新选择文本后改写');
  }
  if (content !== snapshot.content || content.slice(snapshot.start, snapshot.end) !== snapshot.originalText) {
    throw new Error('正文已发生变化，请重新选择文本并生成改写，避免覆盖新稿');
  }
  if (snapshot.start < 0 || snapshot.end <= snapshot.start || snapshot.end > content.length) {
    throw new Error('原选区已失效，请重新选择文本');
  }
  if (!replacement.trim()) throw new Error('候选稿不能为空');
  return content.slice(0, snapshot.start) + replacement + content.slice(snapshot.end);
}
