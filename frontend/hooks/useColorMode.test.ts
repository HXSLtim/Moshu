import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  COLOR_MODE_STORAGE_KEY,
  ColorModeProvider,
  useColorMode,
} from './useColorMode';

function mockMatchMedia(matchesDark: boolean) {
  const listeners = new Set<() => void>();
  const media = {
    matches: matchesDark,
    media: '(prefers-color-scheme: dark)',
    onchange: null,
    addEventListener: vi.fn((_type: string, listener: () => void) => {
      listeners.add(listener);
    }),
    removeEventListener: vi.fn((_type: string, listener: () => void) => {
      listeners.delete(listener);
    }),
    dispatchEvent: vi.fn(),
  };
  vi.stubGlobal('matchMedia', vi.fn(() => media));
  return listeners;
}

describe('useColorMode', () => {
  beforeEach(() => {
    localStorage.clear();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('没有用户选择时跟随系统深色偏好', async () => {
    mockMatchMedia(true);
    const { result } = renderHook(() => useColorMode(), { wrapper: ColorModeProvider });

    await waitFor(() => expect(result.current.mode).toBe('dark'));
    expect(result.current.isDark).toBe(true);
    // 自动跟随系统不应写入手动偏好，后续系统变化仍能生效。
    expect(localStorage.getItem(COLOR_MODE_STORAGE_KEY)).toBeNull();
  });

  it('切换模式后写入 localStorage 并更新 document 配色', async () => {
    mockMatchMedia(false);
    const { result } = renderHook(() => useColorMode(), { wrapper: ColorModeProvider });

    await waitFor(() => expect(result.current.mode).toBe('light'));
    act(() => result.current.toggleColorMode());

    await waitFor(() => {
      expect(result.current.mode).toBe('dark');
      expect(localStorage.getItem(COLOR_MODE_STORAGE_KEY)).toBe('dark');
    });
    expect(document.documentElement.style.colorScheme).toBe('dark');
  });

  it('用户已保存浅色时优先于系统深色偏好', async () => {
    mockMatchMedia(true);
    localStorage.setItem(COLOR_MODE_STORAGE_KEY, 'light');
    const { result } = renderHook(() => useColorMode(), { wrapper: ColorModeProvider });

    await waitFor(() => expect(result.current.mode).toBe('light'));
  });
});
