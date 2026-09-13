import { apiRequest } from '@/lib/api';
import type { Chapter } from '@/types';

export interface Proposal {
  id: string;
  status: 'pending' | 'accepted' | 'rejected' | 'cancelled';
  operation: 'append' | 'replace' | 'create' | 'replace_selection';
  base_version: number;
  base_content_hash: string;
  novel_id?: number;
  novel_lifecycle_id?: string;
  chapter_id?: number | null;
  chapter_lifecycle_id?: string | null;
  content?: string;
  title?: string | null;
  selection_start?: number | null;
  selection_end?: number | null;
}
interface DecisionResult { proposal: Proposal; chapter: Chapter | null; audit_id: string }
const path = (novelId: number, proposalId: string) => `/writing-chat/${novelId}/proposals/${encodeURIComponent(proposalId)}`;
export const writingProposalApi = {
  get(novelId: number, proposalId: string, signal?: AbortSignal) {
    return apiRequest<Proposal>(path(novelId, proposalId), { signal });
  },
  accept(novelId: number, proposalId: string, payload: { request_id: string; expected_version: number; expected_content_hash: string; candidate_content?: string }, signal?: AbortSignal) {
    return apiRequest<DecisionResult>(`${path(novelId, proposalId)}/accept`, { method: 'POST', body: JSON.stringify(payload), signal });
  },
  reject(novelId: number, proposalId: string, requestId: string, signal?: AbortSignal) {
    return apiRequest<DecisionResult>(`${path(novelId, proposalId)}/reject`, { method: 'POST', body: JSON.stringify({ request_id: requestId }), signal });
  },
};
