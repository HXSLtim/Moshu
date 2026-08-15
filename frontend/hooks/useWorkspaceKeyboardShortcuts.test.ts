import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useWorkspaceKeyboardShortcuts } from './useWorkspaceKeyboardShortcuts';

function pressKey(key: string, init: KeyboardEventInit = {}) {
  const event = new KeyboardEvent('keydown', {
    key,
    bubbles: true,
    cancelable: true,
    ...init,
  });
  act(() => {
    document.dispatchEvent(event);
  });
  return event;
}

describe('useWorkspaceKeyboardShortcuts', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });
  afterEach(() => {
    cleanup();
    document.body.innerHTML = '';
  });

  it('Ctrl/⌘+S 触发保存并阻止浏览器默认行为', () => {
    const onSave = vi.fn();
    renderHook(() => useWorkspaceKeyboardShortcuts({ onSave }));

    expect(pressKey('s', { ctrlKey: true }).defaultPrevented).toBe(true);
    expect(pressKey('s', { metaKey: true }).defaultPrevented).toBe(true);
    expect(onSave).toHaveBeenCalledTimes(2);
  });

  it('撤销、重做与 Ctrl+Y 只在存在历史状态时触发', () => {
    const onUndo = vi.fn();
    const onRedo = vi.fn();
    renderHook(() =>
      useWorkspaceKeyboardShortcuts({
        onSave: vi.fn(),
        onUndo,
        onRedo,
        canUndo: true,
        canRedo: true,
      }),
    );

    pressKey('z', { ctrlKey: true });
    pressKey('z', { ctrlKey: true, shiftKey: true });
    pressKey('y', { ctrlKey: true });

    expect(onUndo).toHaveBeenCalledTimes(1);
    expect(onRedo).toHaveBeenCalledTimes(2);
  });

  it('不可撤销时仍阻止浏览器原生撤销，但不会触发回调', () => {
    const onUndo = vi.fn();
    renderHook(() =>
      useWorkspaceKeyboardShortcuts({
        onSave: vi.fn(),
        onUndo,
        canUndo: false,
      }),
    );

    const event = pressKey('z', { ctrlKey: true });
    expect(event.defaultPrevented).toBe(true);
    expect(onUndo).not.toHaveBeenCalled();
  });

  it('⌘/Ctrl+Alt+方向键切换相邻章节', () => {
    const onPreviousChapter = vi.fn();
    const onNextChapter = vi.fn();
    renderHook(() =>
      useWorkspaceKeyboardShortcuts({
        onSave: vi.fn(),
        onPreviousChapter,
        onNextChapter,
        hasPreviousChapter: true,
        hasNextChapter: true,
      }),
    );

    pressKey('ArrowUp', { ctrlKey: true, altKey: true });
    pressKey('ArrowDown', { metaKey: true, altKey: true });

    expect(onPreviousChapter).toHaveBeenCalledTimes(1);
    expect(onNextChapter).toHaveBeenCalledTimes(1);
  });

  it('IME 组合输入、自动重复和禁用状态不会触发动作', () => {
    const onSave = vi.fn();
    const onUndo = vi.fn();
    const { rerender } = renderHook(
      ({ enabled }) =>
        useWorkspaceKeyboardShortcuts({
          enabled,
          onSave,
          onUndo,
          canUndo: true,
        }),
      { initialProps: { enabled: true } },
    );

    pressKey('s', { ctrlKey: true, isComposing: true });
    pressKey('s', { ctrlKey: true, repeat: true });
    expect(onSave).not.toHaveBeenCalled();

    rerender({ enabled: false });
    pressKey('s', { ctrlKey: true });
    pressKey('z', { ctrlKey: true });
    expect(onSave).not.toHaveBeenCalled();
    expect(onUndo).not.toHaveBeenCalled();
  });
});
