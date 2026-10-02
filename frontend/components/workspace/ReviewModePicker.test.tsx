import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ReviewModePicker from './ReviewModePicker';

afterEach(cleanup);

describe('审核模式选择器（批1 归一）', () => {
  it('三档词汇「每次确认/自动采纳/全部采纳」，激活档带选中态', () => {
    render(<ReviewModePicker value="confirm" onChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: '每次确认' }).className).toContain('Mui-selected');
    expect(screen.getByRole('button', { name: '自动采纳' }).className).not.toContain('Mui-selected');
    expect(screen.getByRole('button', { name: '全部采纳' }).className).not.toContain('Mui-selected');
  });

  it('点选切档回传值；disabled 整组不可用', () => {
    const onChange = vi.fn();
    render(<ReviewModePicker value="confirm" onChange={onChange} />);
    fireEvent.click(screen.getByRole('button', { name: '自动采纳' }));
    expect(onChange).toHaveBeenCalledWith('auto');
    cleanup();
    render(<ReviewModePicker value="confirm" onChange={vi.fn()} disabled />);
    expect((screen.getByRole('button', { name: '每次确认' }) as HTMLButtonElement).disabled).toBe(true);
  });
});
