import { apiRequest } from '@/lib/api';
import type {
  CharacterAppearanceCreate,
  CharacterAppearanceResponse,
  CharacterCreate,
  CharacterNetworkResponse,
  CharacterRelationshipCreate,
  CharacterRelationshipResponse,
  CharacterResponse,
  CharacterTimelineResponse,
  CharacterUpdate,
  MCPCharacterAction,
  MCPCharacterResponse,
} from '@/lib/api/generated/model';

/** 人物域门面：/api/characters* 十二个端点的唯一运行时通道；类型来自 orval 生成层，路径不带 /api 前缀。 */
export const charactersApi = {
  list(novelId: number, signal?: AbortSignal): Promise<CharacterResponse[]> {
    return apiRequest<CharacterResponse[]>(`/characters/novel/${novelId}`, { signal });
  },
  get(characterId: number, signal?: AbortSignal): Promise<CharacterResponse> {
    return apiRequest<CharacterResponse>(`/characters/${characterId}`, { signal });
  },
  create(data: CharacterCreate): Promise<CharacterResponse> {
    return apiRequest<CharacterResponse>('/characters', { method: 'POST', body: JSON.stringify(data) });
  },
  update(characterId: number, data: CharacterUpdate): Promise<CharacterResponse> {
    return apiRequest<CharacterResponse>(`/characters/${characterId}`, { method: 'PUT', body: JSON.stringify(data) });
  },
  /** 服务端 204 无载荷。 */
  remove(characterId: number): Promise<void> {
    return apiRequest<void>(`/characters/${characterId}`, { method: 'DELETE' });
  },
  /** 契约即 unknown（服务端未声明载荷形态），第二阶段接入时按实测收敛。 */
  search(novelId: number, q: string, signal?: AbortSignal): Promise<unknown> {
    return apiRequest<unknown>(`/characters/novel/${novelId}/search?q=${encodeURIComponent(q)}`, { signal });
  },
  listRelationships(characterId: number, signal?: AbortSignal): Promise<CharacterRelationshipResponse[]> {
    return apiRequest<CharacterRelationshipResponse[]>(`/characters/${characterId}/relationships`, { signal });
  },
  createRelationship(data: CharacterRelationshipCreate): Promise<CharacterRelationshipResponse> {
    return apiRequest<CharacterRelationshipResponse>('/characters/relationships', { method: 'POST', body: JSON.stringify(data) });
  },
  createAppearance(data: CharacterAppearanceCreate): Promise<CharacterAppearanceResponse> {
    return apiRequest<CharacterAppearanceResponse>('/characters/appearances', { method: 'POST', body: JSON.stringify(data) });
  },
  timeline(characterId: number, signal?: AbortSignal): Promise<CharacterTimelineResponse> {
    return apiRequest<CharacterTimelineResponse>(`/characters/${characterId}/timeline`, { signal });
  },
  network(novelId: number, signal?: AbortSignal): Promise<CharacterNetworkResponse> {
    return apiRequest<CharacterNetworkResponse>(`/characters/novel/${novelId}/network`, { signal });
  },
  executeMcpAction(action: MCPCharacterAction): Promise<MCPCharacterResponse> {
    return apiRequest<MCPCharacterResponse>('/characters/mcp/execute', { method: 'POST', body: JSON.stringify(action) });
  },
};
