import { apiRequest } from '@/lib/api';
import type { ChapterDigestStatus, ChapterRevision, ChapterRevisionSummary, DigestJob } from '@/types/chapterMemory';
import type { Chapter } from '@/types';

const chapterPath = (novelId: number, chapterId: number) => `/novels/${novelId}/chapters/${chapterId}`;

export const chapterMemoryApi = {
  getDigest(novelId: number, chapterId: number, signal?: AbortSignal) {
    return apiRequest<ChapterDigestStatus>(`${chapterPath(novelId, chapterId)}/digest`, { signal });
  },
  rebuild(novelId: number, chapterId: number, signal?: AbortSignal) {
    return apiRequest<DigestJob>(`${chapterPath(novelId, chapterId)}/digest/rebuild`, { method: 'POST', signal });
  },
  listRevisions(novelId: number, chapterId: number, beforeVersion?: number, signal?: AbortSignal) {
    const query = new URLSearchParams({ limit: '20' });
    if (beforeVersion !== undefined) query.set('before_version', String(beforeVersion));
    return apiRequest<ChapterRevisionSummary[]>(`${chapterPath(novelId, chapterId)}/revisions?${query}`, { signal });
  },
  getRevision(novelId: number, revisionId: string, signal?: AbortSignal) {
    return apiRequest<ChapterRevision>(`/novels/${novelId}/revisions/${encodeURIComponent(revisionId)}`, { signal });
  },
  restoreRevision(novelId: number, revisionId: string, data: { expected_version: number; expected_novel_lifecycle_id: string; expected_chapter_lifecycle_id: string }, signal?: AbortSignal) {
    return apiRequest<Chapter>(`/novels/${novelId}/revisions/${encodeURIComponent(revisionId)}/restore`, { method: 'POST', body: JSON.stringify(data), signal });
  },
  cancelJob(jobId: string, signal?: AbortSignal) {
    return apiRequest<DigestJob>(`/memory-jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST', signal });
  },
};
