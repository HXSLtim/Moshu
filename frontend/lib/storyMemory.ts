import { apiRequest } from '@/lib/api';
import type { MemoryCommand, MemorySource, OutlineInput, StateInput, StoryEntity, StoryMemorySnapshot } from '@/types/storyMemory';
const path = (novelId: number) => `/novels/${novelId}/story-memory`;
function command(novelId: number, suffix: string, data: object, signal?: AbortSignal, method = 'POST') {
  return apiRequest<StoryMemorySnapshot>(`${path(novelId)}${suffix}`, { method, body: JSON.stringify(data), signal });
}
export const storyMemoryApi = {
  get(novelId: number, chapter?: number, signal?: AbortSignal) {
    return apiRequest<StoryMemorySnapshot>(`${path(novelId)}${chapter ? `?chapter=${chapter}` : ''}`, { signal });
  },
  createEntity(novelId: number, data: MemoryCommand & Pick<StoryEntity, 'name' | 'kind' | 'description'>, signal?: AbortSignal) { return command(novelId, '/entities', data, signal); },
  saveOutline(novelId: number, id: string | null, data: MemoryCommand & OutlineInput, signal?: AbortSignal) { return command(novelId, `/outline${id ? `/${id}` : ''}`, data, signal, id ? 'PUT' : 'POST'); },
  createState(novelId: number, data: MemoryCommand & StateInput, signal?: AbortSignal) { return command(novelId, '/states', data, signal); },
  replaceState(novelId: number, id: number, data: MemoryCommand & StateInput, signal?: AbortSignal) { return command(novelId, `/states/${id}/replace`, data, signal); },
  createCandidate(novelId: number, data: MemoryCommand & StateInput, signal?: AbortSignal) { return command(novelId, '/candidates', data, signal); },
  decide(novelId: number, id: string, data: MemoryCommand & { action: 'confirm' | 'reject' | 'revoke'; reason: string }, signal?: AbortSignal) { return command(novelId, `/candidates/${id}/decision`, data, signal); },
  extract(novelId: number, data: MemoryCommand & { source_revision_id: string }, signal?: AbortSignal) { return command(novelId, '/extract', data, signal); },
  resolve(novelId: number, kind: 'outline' | 'states', id: string | number, data: MemoryCommand & { source_refs: MemorySource[]; reason: string }, signal?: AbortSignal) { return command(novelId, `/${kind}/${id}/resolve`, data, signal); },
};

export const storyEntityLabel = (entity?: StoryEntity) => entity ? `${entity.name}${entity.description ? `（${entity.description}）` : ''}` : '未知实体';
