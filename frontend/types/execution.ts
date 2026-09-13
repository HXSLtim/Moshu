/**
 * 生成执行计量契约。
 *
 * 字段对应后端 `ExecutionMeter.snapshot()`：用量只放提供方真实返回值，
 * 缺失一律为 null，绝不估算。`usage` 采用全有或全无语义——只要有一轮调用
 * 没拿到用量，或三个 token 字段有任一不是整数，整轮 `usage` 即为 null。
 * 因此前端只渲染下发值，不从字符数、耗时或轮数推断 token。
 */
export interface ExecutionUsage {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

export interface ExecutionCall {
  status: string;
  model: string | null;
  usage: ExecutionUsage | null;
  finish_reason: string | null;
  latency_ms: number | null;
  error_code: string | null;
  streamed?: boolean;
}

export interface ExecutionSnapshot {
  execution_id: string;
  status: string;
  deadline_seconds: number;
  max_model_calls: number;
  model_calls: number;
  latency_ms: number;
  /** null 表示提供方未返回完整用量，不是零消耗。 */
  usage: ExecutionUsage | null;
  transport_attempts: number | null;
  error_code: string | null;
  calls: ExecutionCall[];
}

/** 用量三项都是整数才可展示；缺失即视为未知。 */
export function readExecutionUsage(usage?: ExecutionUsage | null): ExecutionUsage | null {
  if (!usage) return null;
  const values = [usage.input_tokens, usage.output_tokens, usage.total_tokens];
  if (!values.every((value) => Number.isInteger(value))) return null;
  return usage;
}
