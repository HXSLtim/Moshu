export interface ChapterDigestSource {
  kind: 'chapter_digest';
  id: string;
  title: string;
  chapter_id: number;
  chapter_number: number;
  source_revision_id: string;
  source_version: number;
  content_hash: string;
}

export interface ContextManifest {
  version: 1;
  scope: {
    novel_id: number;
    novel_lifecycle_id: string;
    target_chapter: number | null;
    current_day: number | null;
  };
  sources: ChapterDigestSource[];
  structured_sources?: {
    kind: 'core_state' | 'outline_node' | 'source_excerpt';
    id: string;
    title: string;
    text: string;
    effective_chapter: number | null;
    source_refs: { revision_id: string; chapter_id: number; chapter_number: number; source_version: number; content_hash: string; start: number }[];
  }[];
  warnings: string[];
  omitted: Record<string, number>;
  fingerprint: string;
}
