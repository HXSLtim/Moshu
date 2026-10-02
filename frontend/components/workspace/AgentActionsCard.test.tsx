import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import AgentActionsCard, { AgentActionChips } from './AgentActionsCard';
import type { AgentAction } from '@/types/writingChat';

afterEach(cleanup);

describe('Agent 动作卡状态章（批1 收编 StatusChip）', () => {
  it('已写入=success 描边、已跳过=灰描边（正常裁决），不再手调 18px 微章', () => {
    const actions: AgentAction[] = [
      { kind: 'fact', subject: '林夏', attribute: '身份', value: '旅人', decision: 'applied' },
      { kind: 'fact', subject: '守将', attribute: '身份', value: '将军', decision: 'skipped' },
    ];
    const { container } = render(
      <AgentActionsCard novelId={7} turnId={3} actions={actions} uncertainties={[]} onDecided={vi.fn()} />,
    );
    const applied = screen.getByText('已写入').closest('.MuiChip-root') as HTMLElement;
    const skipped = screen.getByText('已跳过').closest('.MuiChip-root') as HTMLElement;
    expect(applied.className).toContain('MuiChip-colorSuccess');
    expect(applied.className).toContain('MuiChip-outlined');
    expect(skipped.className).toContain('MuiChip-colorDefault');
    expect(skipped.className).toContain('MuiChip-outlined');
    // 随手字号/高度散点清零：章尺寸由原语统一
    expect(container.querySelector('[style*="height: 18px"]')).toBeNull();
  });

  it('摘要章为 neutral 属性档，不占状态色', () => {
    const actions: AgentAction[] = [{ kind: 'fact', subject: '林夏', attribute: '身份', value: '旅人' }];
    render(<AgentActionChips actions={actions} />);
    const chip = screen.getByText('林夏 的 身份：旅人').closest('.MuiChip-root') as HTMLElement;
    expect(chip.className).toContain('MuiChip-colorDefault');
    expect(chip.className).toContain('MuiChip-outlined');
  });
});
