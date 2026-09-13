export interface ChapterRevisionSummary {
  id: string;
  version: number;
  chapter_number: number;
  title: string;
  content_hash: string;
  created_at: string;
}

export interface ChapterRevision extends ChapterRevisionSummary {
  chapter_id: number;
  content: string;
}

export interface DigestJob {
  id: string;
  state: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'superseded';
  attempts: number;
  max_attempts: number;
  error_code: string | null;
  error_message: string | null;
}

export interface ChapterDigest {
  id: string;
  source_revision_id: string;
  source_version: number;
  summary: string;
  participants: string[];
  events: string[];
  state_change_candidates: string[];
  open_threads: string[];
  source_refs: { revision_id: string; start: number; end: number; quote: string; content_hash: string }[];
  created_at: string;
}

export interface ChapterDigestStatus {
  status: 'ready' | 'stale' | 'missing';
  current_version: number;
  worker_enabled: boolean;
  digest: ChapterDigest | null;
  job: DigestJob | null;
}
