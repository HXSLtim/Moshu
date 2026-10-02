/**
 * 用户类型定义
 */
export interface User {
  id: number;
  username: string;
  email: string;
  is_active: boolean;
  created_at: string;
}

/**
 * 小说类型定义
 */
export interface Novel {
  id: number;
  rag_lifecycle_id?: string;
  title: string;
  genre?: string;
  description?: string;
  worldview?: string;
  user_id: number;
  created_at: string;
  updated_at?: string;
}

export interface StyleSample {
  id: number;
  novel_id: number;
  name: string;
  sample_preview: string;
  style_features: string[];
  created_at: string;
}

/**
 * 章节类型定义
 */
export interface Chapter {
  id: number;
  rag_lifecycle_id?: string;
  novel_id: number;
  chapter_number: number;
  title: string;
  content: string;
  word_count: number;
  /**
   * 章节乐观锁版本。每次持久化更新后由服务端递增。
   */
  version: number;
  created_at: string;
  updated_at?: string;
}

/**
 * 章节列表只使用摘要，避免长篇小说在打开工作台时下载全部正文。
 */
export interface ChapterSummary {
  id: number;
  novel_id: number;
  chapter_number: number;
  title: string;
  word_count: number;
  version: number;
  created_at: string;
  updated_at?: string;
}

export interface ChapterSummaryPage {
  items: ChapterSummary[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
}

export interface NovelStatistics {
  novel_id: number;
  chapter_count: number;
  total_words: number;
}

export interface NovelStatisticsResponse {
  items: NovelStatistics[];
}

export interface GenerationFinalConsistency {
  status: 'passed' | 'incomplete' | 'conflict' | 'conflict_after_retries';
  has_conflict: boolean;
  retry_exhausted: boolean;
  is_complete: boolean;
  checks_skipped: string[];
  violations: string[];
}

export interface GenerationMetadata {
  style_features?: string[];
  workflow_trace?: AgentWorkflowTrace | null;
  agents?: string[];
  agent_names?: string[];
  consistency_checks?: unknown[];
  retry_count?: number;
  final_consistency?: GenerationFinalConsistency;
}

/**
 * 登录请求
 */
export interface LoginRequest {
  username: string;
  password: string;
}

/**
 * 注册请求
 */
export interface RegisterRequest {
  username: string;
  email: string;
  password: string;
}

/**
 * 认证响应
 */
export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: User;
}

/**
 * 小说创建请求
 */
export interface NovelCreate {
  title: string;
  genre?: string;
  description?: string;
  worldview?: string;
}

export interface IdeaParseResult {
  title: string;
  genre: string;
  description: string;
  worldview: string;
  planned_chapters: number;
  arcs: Array<{ name: string; chapter_start: number; chapter_end: number; summary: string }>;
  characters: Array<{ name: string; role: string; personality: string; goal: string }>;
  opening_outline: Array<{ chapter_number: number; title: string; summary: string; conflict: string; outcome: string }>;
  plot_hooks: string[];
  uncertainties: string[];
}

/**
 * 章节创建请求
 */
export interface ChapterCreate {
  chapter_number: number;
  title: string;
  content: string;
}

/**
 * 工作台更新章节时携带读取到的版本，防止旧请求覆盖新稿。
 */
export interface ChapterUpdate {
  expected_novel_lifecycle_id?: string;
  expected_chapter_lifecycle_id?: string;
  title?: string;
  content?: string;
  chapter_number?: number;
  expected_version: number;
}

/**
 * 新建下一章时章节号由服务端在事务中分配。
 */
export interface ChapterNextCreate {
  title?: string;
  content?: string;
}

/**
 * 工作流追踪类型:自 OpenAPI 契约生成,保留旧名作为别名。
 * 契约变更时经 `npm run codegen` 同步,手写副本已删除。
 */
import type { WorkflowStep } from '@/lib/api/generated/model/workflowStep';
import type { WorkflowTrace } from '@/lib/api/generated/model/workflowTrace';

export type AgentWorkflowStep = WorkflowStep;
export type AgentWorkflowTrace = WorkflowTrace;
export type { WorkflowStep, WorkflowTrace };
