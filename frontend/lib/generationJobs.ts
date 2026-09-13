import { apiRequest } from '@/lib/api';

export type GenerationKind = 'chat' | 'generate' | 'continue' | 'rewrite' | 'auto_chapter' | 'outline' | 'character';
export interface GenerationJob<T = Record<string, unknown>> {
  id: string;
  request_id: string;
  novel_id: number;
  novel_lifecycle_id: string;
  chapter_id: number | null;
  chapter_lifecycle_id?: string | null;
  chapter_title?: string | null;
  message?: string | null;
  mode?: string | null;
  kind: GenerationKind;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  result: T | null;
  error: string | null;
  error_code?: string | null;
  execution?: Record<string, unknown> | null;
  created_at: string;
  finished_at: string | null;
}
export const isGenerationPending = (job: GenerationJob<unknown>) => job.status === 'queued' || job.status === 'running';
const path = (id: string, novelId: number) => `/generation/jobs/${encodeURIComponent(id)}?novel_id=${novelId}`;
export const generationJobsApi = {
  create<T>(data: { request_id: string; kind: GenerationKind; novel_id: number; expected_novel_lifecycle_id: string; payload: object }, signal?: AbortSignal) {
    return apiRequest<GenerationJob<T>>('/generation/jobs', { method: 'POST', body: JSON.stringify(data), signal });
  },
  list<T>(novelId: number, kind?: GenerationKind, signal?: AbortSignal, chapterId?: number | null) {
    return apiRequest<GenerationJob<T>[]>(`/generation/jobs?novel_id=${novelId}&limit=30${kind ? `&kind=${kind}` : ''}${chapterId === undefined || chapterId === null ? '' : `&chapter_id=${chapterId}`}`, { signal });
  },
  get<T>(novelId: number, id: string, signal?: AbortSignal) { return apiRequest<GenerationJob<T>>(path(id, novelId), { signal }); },
  stop<T>(novelId: number, id: string, signal?: AbortSignal) {
    return apiRequest<GenerationJob<T>>(`/generation/jobs/${encodeURIComponent(id)}/stop?novel_id=${novelId}`, { method: 'POST', signal });
  },
  retry<T>(novelId: number, id: string, requestId: string, signal?: AbortSignal) {
    return apiRequest<GenerationJob<T>>(`/generation/jobs/${encodeURIComponent(id)}/retry?novel_id=${novelId}`, { method: 'POST', body: JSON.stringify({ request_id: requestId }), signal });
  },
};
