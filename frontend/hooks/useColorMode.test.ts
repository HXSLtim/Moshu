import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  COLOR_MODE_STORAGE_KEY,
  ColorModeProvider,
  useColorMode,
} from './useColorMode';

describe('useColorMode', () => {
  beforeEach(() => {
    localStorage.clear();
  });
  afterEach(() => {
    localStorage.clear();
  });

  it('无存储偏好时默认深色，不跟随系统且不写入手动偏好', async () => {
    const { result } = renderHook(() => useColorMode(), { wrapper: ColorModeProvider });

    await waitFor(() => expect(result.current.mode).toBe('dark'));
    expect(result.current.isDark).toBe(true);
    // 深色默认不写入手动偏好，避免把「没选过」固化成选择。
    expect(localStorage.getItem(COLOR_MODE_STORAGE_KEY)).toBeNull();
  });

  it('切换模式后写入 localStorage 并更新 document 配色', async () => {
    const { result } = renderHook(() => useColorMode(), { wrapper: ColorModeProvider });

    await waitFor(() => expect(result.current.mode).toBe('dark'));
    act(() => result.current.toggleColorMode());

    await waitFor(() => {
      expect(result.current.mode).toBe('light');
      expect(localStorage.getItem(COLOR_MODE_STORAGE_KEY)).toBe('light');
    });
    expect(document.documentElement.style.colorScheme).toBe('light');
  });

  it('已存浅色偏好的老用户不被深色默认迁移', async () => {
    localStorage.setItem(COLOR_MODE_STORAGE_KEY, 'light');
    const { result } = renderHook(() => useColorMode(), { wrapper: ColorModeProvider });

    await waitFor(() => expect(result.current.mode).toBe('light'));
  });

  it('存储值非法时按无偏好兜底深色', async () => {
    localStorage.setItem(COLOR_MODE_STORAGE_KEY, 'sepia');
    const { result } = renderHook(() => useColorMode(), { wrapper: ColorModeProvider });

    await waitFor(() => expect(result.current.mode).toBe('dark'));
  });
});
