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

export const COLOR_MODE_STORAGE_KEY = 'moshu-color-mode';

function readStoredMode(): PaletteMode | null {
  if (typeof window === 'undefined') return null;
  try {
    const stored = window.localStorage.getItem(COLOR_MODE_STORAGE_KEY);
    return stored === 'light' || stored === 'dark' ? stored : null;
  } catch {
    return null;
  }
}

interface ColorModeValue {
  mode: PaletteMode;
  isDark: boolean;
  toggleColorMode: () => void;
  setColorMode: (mode: PaletteMode) => void;
}

const ColorModeContext = createContext<ColorModeValue | null>(null);

function useColorModeState(): ColorModeValue {
  // 服务端与客户端首帧统一渲染深色（v2 深色优先），避免 hydration 不匹配；挂载后再应用偏好。
  const [mode, setMode] = useState<PaletteMode>('dark');
  const hasManualPreferenceRef = useRef(false);

  useEffect(() => {
    // 解析序=存储>兜底深；prefers-color-scheme 不进默认链（GUIDE v2 修订：
    // 默认=无条件深色不跟随系统，纸墨浅色由作者显式选择；系统跟随列远期可选增强）。
    const stored = readStoredMode();
    if (stored) setMode((current) => (current === stored ? current : stored));
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
 * 全局主题模式：优先用户存储选择，否则默认深色；不跟随系统偏好
 * （GUIDE v2 修订：默认=无条件深色，浅色档由作者显式选择）。
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
