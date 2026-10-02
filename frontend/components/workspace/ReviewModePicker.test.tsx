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

  it('统一说明句与悬停副文本（快裁：同句两处、三档各一句）', async () => {
    render(<ReviewModePicker value="auto" onChange={vi.fn()} />);
    expect(screen.getByText('审核模式：AI 的改稿怎么入库，按本书保存。')).toBeTruthy();
    fireEvent.mouseOver(screen.getByRole('button', { name: '自动采纳' }));
    expect(await screen.findByText('通过一致性检查的直接写入，有疑问的留给你决定。')).toBeTruthy();
  });

  it('对话栏密度档 caption=false：不渲染常驻说明行，只留档位悬停（pm 裁量）', () => {
    render(<ReviewModePicker value="confirm" onChange={vi.fn()} caption={false} />);
    expect(screen.queryByText('审核模式：AI 的改稿怎么入库，按本书保存。')).toBeNull();
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
