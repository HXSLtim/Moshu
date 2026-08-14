import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useEditHistory } from './useEditHistory';

describe('useEditHistory', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('把连续输入合并为一个 400ms 编辑批次', () => {
    const { result } = renderHook(() => useEditHistory({ batchDelay: 400 }));

    act(() => {
      result.current.clearHistory('初始');
      result.current.addToHistory('第一键');
      result.current.addToHistory('最终文本');
      vi.advanceTimersByTime(399);
    });
    expect(result.current.history).toEqual(['初始']);

    act(() => vi.advanceTimersByTime(1));
    expect(result.current.history).toEqual(['初始', '最终文本']);
  });

  it('同时限制历史条数和字符预算', () => {
    const { result } = renderHook(() =>
      useEditHistory({ maxHistorySize: 3, maxCharacterBudget: 8 }),
    );

    act(() => {
      result.current.clearHistory('1111');
      result.current.addToHistory('2222', { immediate: true });
      result.current.addToHistory('3333', { immediate: true });
    });

    expect(result.current.history).toEqual(['2222', '3333']);
    expect(result.current.historyIndex).toBe(1);
  });

  it('撤销前会先提交尚未到期的编辑批次', () => {
    const { result } = renderHook(() => useEditHistory());
    act(() => {
      result.current.clearHistory('旧稿');
      result.current.addToHistory('新稿');
    });

    let restored: string | null = null;
    act(() => {
      restored = result.current.undo();
    });

    expect(restored).toBe('旧稿');
    expect(result.current.canRedo).toBe(true);
  });
});
