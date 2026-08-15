'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import type { PaletteMode } from '@mui/material';

export const COLOR_MODE_STORAGE_KEY = 'nai-color-mode';

function readStoredMode(): PaletteMode | null {
  if (typeof window === 'undefined') return null;
  try {
    const stored = window.localStorage.getItem(COLOR_MODE_STORAGE_KEY);
    return stored === 'light' || stored === 'dark' ? stored : null;
  } catch {
    return null;
  }
}

function readSystemMode(): PaletteMode {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return 'light';
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

interface ColorModeValue {
  mode: PaletteMode;
  isDark: boolean;
  toggleColorMode: () => void;
  setColorMode: (mode: PaletteMode) => void;
}

const ColorModeContext = createContext<ColorModeValue | null>(null);

function useColorModeState(): ColorModeValue {
  // 服务端与客户端首帧统一渲染浅色，避免 hydration 不匹配；挂载后再应用偏好。
  const [mode, setMode] = useState<PaletteMode>('light');
  const hasManualPreferenceRef = useRef(false);

  useEffect(() => {
    const stored = readStoredMode();
    const systemMode = readSystemMode();
    const nextMode = stored ?? systemMode;
    setMode((current) => (current === nextMode ? current : nextMode));

    const media = typeof window.matchMedia === 'function'
      ? window.matchMedia('(prefers-color-scheme: dark)')
      : null;
    const handleSystemChange = () => {
      if (!readStoredMode()) setMode(readSystemMode());
    };
    media?.addEventListener('change', handleSystemChange);
    return () => media?.removeEventListener('change', handleSystemChange);
  }, []);

  useEffect(() => {
    document.documentElement.style.colorScheme = mode;
    if (!hasManualPreferenceRef.current) return;
    try {
      window.localStorage.setItem(COLOR_MODE_STORAGE_KEY, mode);
    } catch {
      // 隐私模式下写入失败不应阻断主题切换。
    }
  }, [mode]);

  const setColorMode = useCallback((nextMode: PaletteMode) => {
    hasManualPreferenceRef.current = true;
    setMode(nextMode);
  }, []);

  const toggleColorMode = useCallback(() => {
    hasManualPreferenceRef.current = true;
    setMode((current) => (current === 'light' ? 'dark' : 'light'));
  }, []);

  return useMemo(
    () => ({
      mode,
      isDark: mode === 'dark',
      toggleColorMode,
      setColorMode,
    }),
    [mode, setColorMode, toggleColorMode],
  );
}

export function ColorModeProvider({ children }: { children: ReactNode }) {
  const value = useColorModeState();
  return (
    <ColorModeContext.Provider value={value}>
      {children}
    </ColorModeContext.Provider>
  );
}

/**
 * 全局纸墨主题模式：优先用户选择，否则跟随系统偏好。
 *
 * 必须在 `ColorModeProvider` 内使用，保证切换按钮与 ThemeProvider
 * 读取的是同一份模式状态。
 */
export function useColorMode(): ColorModeValue {
  const value = useContext(ColorModeContext);
  if (!value) {
    throw new Error('useColorMode 必须在 ColorModeProvider 内使用');
  }
  return value;
}
