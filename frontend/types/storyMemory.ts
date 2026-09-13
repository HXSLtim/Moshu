export interface MemorySource { revision_id: string; quote: string; start: number; end?: number; content_hash?: string; quote_hash?: string }
export interface StoryEntity { id: string; name: string; description?: string; kind: 'character' | 'item' | 'location' | 'organization' }
export interface OutlineNode {
  id: string; parent_id: string | null; kind: 'volume' | 'chapter' | 'scene'; plot_status: 'planned' | 'occurred';
  chapter_number: number | null; title: string; conflict: string; outcome: string;
  origin: 'author' | 'ai'; source_refs: MemorySource[]; source_status: 'ready' | 'needs_review';
}
export interface EntityState {
  id: number; entity_id: string; subject: string; attribute: string; value: string; value_entity_id: string | null;
  chapter_established: number | null; retired_chapter: number | null; status: string;
  source_status: 'ready' | 'needs_review'; origin: 'author' | 'ai'; source_refs: MemorySource[];
}
export interface StateCandidate {
  id: string; entity_id: string; attribute: string; value: string; value_entity_id: string | null;
  effective_chapter: number; source_refs: MemorySource[]; status: 'pending' | 'confirmed' | 'rejected' | 'revoked';
  source_status: 'ready' | 'needs_review'; reason: string;
}
export interface StoryMemorySnapshot {
  version: number; novel_lifecycle_id: string; entities: StoryEntity[]; outline_nodes: OutlineNode[];
  states: EntityState[]; state_history: EntityState[]; candidates: StateCandidate[]; warnings: string[];
}
export interface MemoryCommand { request_id: string; expected_version: number; novel_lifecycle_id: string }
export type OutlineInput = Pick<OutlineNode, 'parent_id' | 'kind' | 'plot_status' | 'chapter_number' | 'title' | 'conflict' | 'outcome' | 'source_refs'>;
export interface StateInput { entity_id: string; attribute: string; value: string; value_entity_id: string | null; effective_chapter: number; source_refs: MemorySource[] }
