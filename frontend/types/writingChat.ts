import type { ContextManifest } from '@/types/context';
import type { ExecutionSnapshot } from '@/types/execution';

export type WritingMode = 'discuss' | 'continue' | 'advanced_continue' | 'rewrite' | 'outline' | 'character' | 'check' | 'new_chapter';

/**
 * Agent 在交流中自己判断需要写入的设定动作。
 * 作者不必选模式；模型只负责提议，确认后才落库。
 */
export type AgentAction =
  | { kind: 'project_info'; genre: string | null; description: string | null; worldview: string | null }
  | { kind: 'entity'; name: string; entity_kind: 'character' | 'item' | 'location' | 'organization'; description: string }
  | { kind: 'fact'; subject: string; attribute: string; value: string }
  | { kind: 'outline'; node_kind: 'volume' | 'chapter'; title: string; chapter_number: number | null; summary: string };

export interface AgentTurnResult {
  reply: string;
  actions: AgentAction[];
  uncertainties: string[];
  decided_mode?: WritingMode;
  manuscript?: { operation: 'append' | 'rewrite' | 'create'; content: string; title: string | null };
}
export interface WritingTurn {
  id: number;
  /** 尚未落库的消息在本地历史中的顺序。 */
  local_order?: number;
  /** 已持久排队但尚未建立对话轮次时，保留真实任务身份。 */
  job_id?: string;
  job_status?: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  proposal_id?: string | null;
  result?: Record<string, unknown> | null;
  /** 本轮真实执行计量；缺失表示未记录，其中 usage 可能为 null（提供方未返回）。 */
  execution?: ExecutionSnapshot | null;
  base_version?: number | null;
  novel_lifecycle_id?: string | null;
  chapter_lifecycle_id?: string | null;
  request_id: string;
  novel_id: number;
  chapter_id: number;
  chapter_title: string;
  mode: WritingMode;
  user_text: string;
  assistant_text: string;
  base_content_hash: string;
  status: 'pending' | 'completed' | 'failed' | 'cancelled';
  error: string | null;
  created_at: string;
  /** 缺失表示该历史轮次未记录生成时使用的来源。 */
  context_manifest?: ContextManifest | null;
}
export interface WritingTurnCreate {
  expected_version?: number;
  expected_novel_lifecycle_id?: string;
  expected_chapter_lifecycle_id?: string;
  options?: { target_length?: number; target_chapters?: number; character_type?: string; current_day?: number | null };
  request_id: string;
  chapter_id: number;
  mode: WritingMode;
  message: string;
  current_content: string;
}
