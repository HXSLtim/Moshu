/** 本机草稿使用服务端生命周期隔离，旧格式只作为导出材料保留。 */
export interface DraftIdentity {
  userId: number;
  novelLifecycleId: string;
  chapterLifecycleId: string;
}
export interface ChapterDraftBackup {
  novelId: number;
  chapterId: number;
  title: string;
  content: string;
  version: number;
  savedAt: string;
  identity?: DraftIdentity;
  schemaVersion?: 2;
}
export interface RecoverableDraft {
  storageKey: string;
  draft: ChapterDraftBackup;
  reason: 'legacy' | 'different_account' | 'different_lifecycle' | 'older';
}
const PREFIX = 'nai_chapter_draft_';

export function chapterDraftKey(novelId: number, chapterId: number, identity: DraftIdentity): string {
  return `${PREFIX}v2_${encodeURIComponent(JSON.stringify([identity.userId, novelId, identity.novelLifecycleId, chapterId, identity.chapterLifecycleId]))}`;
}
export function sameDraftIdentity(left?: DraftIdentity | null, right?: DraftIdentity | null): boolean {
  return Boolean(left && right && left.userId === right.userId && left.novelLifecycleId === right.novelLifecycleId && left.chapterLifecycleId === right.chapterLifecycleId);
}
function parse(raw: string | null): ChapterDraftBackup | null {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as ChapterDraftBackup;
    if (!Number.isInteger(value.novelId) || !Number.isInteger(value.chapterId) || typeof value.title !== 'string' || typeof value.content !== 'string' || !Number.isInteger(value.version) || typeof value.savedAt !== 'string') return null;
    return value;
  } catch { return null; }
}
export function readChapterDraft(novelId: number, chapterId: number, identity: DraftIdentity | null): ChapterDraftBackup | null {
  if (!identity || typeof window === 'undefined') return null;
  try {
    const draft = parse(localStorage.getItem(chapterDraftKey(novelId, chapterId, identity)));
    return draft?.schemaVersion === 2 && draft.novelId === novelId && draft.chapterId === chapterId && sameDraftIdentity(draft.identity, identity) ? draft : null;
  } catch { return null; }
}
export function listRecoveryDrafts(novelId: number, chapterId: number, identity: DraftIdentity | null): RecoverableDraft[] {
  if (typeof window === 'undefined') return [];
  try {
    const result: RecoverableDraft[] = [];
    for (let i = 0; i < localStorage.length; i += 1) {
      const storageKey = localStorage.key(i);
      if (!storageKey?.startsWith(PREFIX)) continue;
      const draft = parse(localStorage.getItem(storageKey));
      if (!draft || draft.novelId !== novelId || draft.chapterId !== chapterId) continue;
      if (sameDraftIdentity(draft.identity, identity) && draft.schemaVersion === 2 && !storageKey.includes('_recovery_')) continue;
      result.push({ storageKey, draft, reason: !draft.identity || draft.schemaVersion !== 2 ? 'legacy' : draft.identity.userId !== identity?.userId ? 'different_account' : sameDraftIdentity(draft.identity, identity) ? 'older' : 'different_lifecycle' });
    }
    return result;
  } catch { return []; }
}
export function writeChapterDraft(novelId: number, snapshot: { chapterId: number; title: string; content: string; expectedVersion?: number }, version: number, identity: DraftIdentity | null): boolean {
  if (!identity || typeof window === 'undefined') return false;
  try {
    const draft: ChapterDraftBackup = { novelId, ...snapshot, version, savedAt: new Date().toISOString(), identity, schemaVersion: 2 };
    localStorage.setItem(chapterDraftKey(novelId, snapshot.chapterId, identity), JSON.stringify(draft));
    return true;
  } catch { return false; }
}
export function removeChapterDraft(novelId: number, chapterId: number, identity: DraftIdentity | null): void {
  if (!identity || typeof window === 'undefined') return;
  try { localStorage.removeItem(chapterDraftKey(novelId, chapterId, identity)); } catch { /* 清理失败不影响已保存原文。 */ }
}

export function archiveChapterDraft(novelId: number, chapterId: number, identity: DraftIdentity, draft: ChapterDraftBackup): RecoverableDraft {
  const activeKey = chapterDraftKey(novelId, chapterId, identity);
  const storageKey = `${activeKey}_recovery_${encodeURIComponent(draft.savedAt)}_${crypto.randomUUID()}`;
  // 先复制再移除当前备份槽，后续编辑不能覆盖尚未审阅的旧稿。
  localStorage.setItem(storageKey, JSON.stringify(draft));
  localStorage.removeItem(activeKey);
  return { storageKey, draft, reason: 'older' };
}
