import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import ExecutionUsageLine from './ExecutionUsageLine';
import type { ExecutionSnapshot } from '@/types/execution';

const snapshot = (overrides: Partial<ExecutionSnapshot> = {}): ExecutionSnapshot => ({
  execution_id: 'exec-1',
  status: 'completed',
  deadline_seconds: 390,
  max_model_calls: 1,
  model_calls: 1,
  latency_ms: 4847,
  usage: { input_tokens: 1827, output_tokens: 536, total_tokens: 2363 },
  transport_attempts: null,
  error_code: null,
  calls: [],
  ...overrides,
});

afterEach(cleanup);

describe('本轮真实用量展示', () => {
  it('提供方返回用量时展示真实 token 数', () => {
    render(<ExecutionUsageLine execution={snapshot()} />);
    expect(screen.getByText(/输入 1827 \/ 输出 536 tokens（提供方返回）/)).toBeTruthy();
  });

  it('用量缺失时说明未返回，不用字符数或耗时推算 token', () => {
    render(<ExecutionUsageLine execution={snapshot({ usage: null, latency_ms: 9999, model_calls: 3 })} />);
    expect(screen.getByText(/提供方未返回本轮用量/)).toBeTruthy();
    // 只有轮数可核实；延迟与字符预算都不能换算成 token。
    expect(screen.getByText(/共 3 次模型调用/)).toBeTruthy();
    expect(screen.queryByText(/tokens$/)).toBeNull();
  });

  it('token 字段不是整数时按未知处理，不展示伪造用量', () => {
    render(<ExecutionUsageLine execution={snapshot({
      usage: { input_tokens: 1.5, output_tokens: 2, total_tokens: 3 },
    })} />);
    expect(screen.getByText(/提供方未返回本轮用量/)).toBeTruthy();
  });

  it('单次调用不重复标注轮数，无执行记录时不渲染', () => {
    const { container } = render(<ExecutionUsageLine execution={snapshot()} />);
    expect(container.textContent).not.toContain('共 1 次');
    const { container: empty } = render(<ExecutionUsageLine execution={null} />);
    expect(empty.textContent).toBe('');
  });
});
