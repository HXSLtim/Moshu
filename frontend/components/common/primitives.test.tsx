import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { EmptyState, SectionHeader, StatusChip } from './primitives';

afterEach(cleanup);

describe('共享原语三件套', () => {
  it('SectionHeader 渲染标题与动作槽，divider 可关', () => {
    const { rerender } = render(<SectionHeader title="人物档案" action={<button>动作</button>} />);
    expect(screen.getByText('人物档案')).toBeTruthy();
    expect(screen.getByRole('button', { name: '动作' })).toBeTruthy();
    expect(document.querySelector('.MuiDivider-root')).toBeTruthy();
    rerender(<SectionHeader title="无分隔" divider={false} />);
    expect(document.querySelector('.MuiDivider-root')).toBeNull();
  });

  it('EmptyState 渲染标题、引导与动作槽，缺省 info 形态', () => {
    render(<EmptyState title="还没有人物档案。" hint="确认写入后出现在这里。" action={<button>去对话</button>} />);
    expect(screen.getByText('还没有人物档案。')).toBeTruthy();
    expect(screen.getByText('确认写入后出现在这里。')).toBeTruthy();
    expect(screen.getByRole('button', { name: '去对话' })).toBeTruthy();
    expect(document.querySelector('.MuiAlert-standardInfo')).toBeTruthy();
  });

  it('StatusChip 按状态色语义表映射 tone：实心=当下状态，描边=属性既成', () => {
    const { container } = render(<StatusChip tone="achieved" label="已写入" />);
    expect(container.querySelector('.MuiChip-colorSuccess')).toBeTruthy();
    expect(container.querySelector('.MuiChip-outlined')).toBeTruthy();
    cleanup();
    const error = render(<StatusChip tone="error" label="保存失败" />);
    expect(error.container.querySelector('.MuiChip-colorError')).toBeTruthy();
    expect(error.container.querySelector('.MuiChip-filled')).toBeTruthy();
    cleanup();
    const stale = render(<StatusChip tone="stale" label="已失效" />);
    expect(stale.container.querySelector('.MuiChip-colorWarning')).toBeTruthy();
    expect(stale.container.querySelector('.MuiChip-outlined')).toBeTruthy();
    cleanup();
    const neutral = render(<StatusChip tone="neutral" size="small" label="主力" />);
    expect(neutral.container.querySelector('.MuiChip-colorDefault')).toBeTruthy();
    expect(neutral.container.querySelector('.MuiChip-outlined')).toBeTruthy();
  });
});
