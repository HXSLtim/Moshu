'use client';

import { Typography } from '@mui/material';
import { readExecutionUsage, type ExecutionSnapshot } from '@/types/execution';

interface Props {
  execution?: ExecutionSnapshot | null;
}

/**
 * 展示本轮真实模型用量。
 *
 * 只显示提供方返回的用量；缺失时明确说明未返回，不显示任何估算值——
 * 字符预算不等于 token 计费，耗时与轮数也不能反推 token。
 */
export default function ExecutionUsageLine({ execution }: Props) {
  if (!execution) return null;
  const usage = readExecutionUsage(execution.usage);
  const calls = Number.isInteger(execution.model_calls) && execution.model_calls > 1
    ? ` · 共 ${execution.model_calls} 次模型调用`
    : '';
  return <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
    {usage
      ? `本轮用量 输入 ${usage.input_tokens} / 输出 ${usage.output_tokens} 字${calls}`
      : `提供方未返回本轮用量，无法展示 token 消耗${calls}`}
  </Typography>;
}
