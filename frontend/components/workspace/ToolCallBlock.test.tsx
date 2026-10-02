import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ToolCallBlock from './ToolCallBlock';

describe('工具状态行', () => {
  it('write_manuscript 显示中文标签而非裸工具名', () => {
    render(<ToolCallBlock event={{ name: 'write_manuscript', status: 'drafted' }} />);
    expect(screen.getByText('已起草正文')).toBeTruthy();
    expect(screen.queryByText(/write_manuscript/)).toBeNull();
  });

  it('执行中显示「正在起草正文…」', () => {
    render(<ToolCallBlock event={{ name: 'write_manuscript', status: 'running' }} />);
    expect(screen.getByText('正在起草正文…')).toBeTruthy();
  });

  it('read_chapter 显示中文标签而非裸工具名', () => {
    render(<ToolCallBlock event={{ name: 'read_chapter', status: 'running' }} />);
    expect(screen.getByText('正在阅读正文…')).toBeTruthy();
    expect(screen.queryByText(/read_chapter\b/)).toBeNull();
  });

  it('read_chapter 完成态显示「已阅读正文」', () => {
    render(<ToolCallBlock event={{ name: 'read_chapter', status: 'read' }} />);
    expect(screen.getByText('已阅读正文')).toBeTruthy();
  });
});
