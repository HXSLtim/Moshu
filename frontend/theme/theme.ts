'use client';

import { createTheme, PaletteMode } from '@mui/material/styles';
import type { Shadows } from '@mui/material/styles';

// 扩展 token：内嵌卡/条目组的 subtle 底色（GUIDE「扩展 token」节，批1 落值）。
declare module '@mui/material/styles' {
  interface TypeBackground {
    subtle: string;
  }
}

// 字体栈（GUIDE v2「字体系统」节，批0）：UI 中文走系统栈，零在线字体；数字/拉丁/
// 代码感元素取 mono 栈（字数统计、章号、版本号、时间戳、用量行等场景显式取用，
// 组件落地随批4）。小说正文阅读区禁 mono，保持 16px/1.75 阅读体。
export const UI_FONT_STACK = [
  '-apple-system',
  'BlinkMacSystemFont',
  '"Segoe UI"',
  'Roboto',
  '"Noto Sans SC"',
  '"PingFang SC"',
  '"Microsoft YaHei"',
  'sans-serif',
].join(',');

export const MONO_FONT_STACK = [
  'ui-monospace',
  '"SF Mono"',
  '"JetBrains Mono"',
  'Consolas',
  'monospace',
].join(',');

// 全站零 elevation（GUIDE v2「形体语言」节，批0）：阴影通道整列置空，
// depth 靠层级与 1px 边框立，不靠投影。
const noShadows = Array(25).fill('none') as Shadows;

/**
 * 冷灰配色方案 - 浅色模式（纸墨日间档，v2 保留）
 */
const lightPalette = {
  primary: {
    main: '#006C52',        // 低饱和绿
    contrastText: '#FFFFFF',
    container: '#D4F5E9',
  },
  secondary: {
    main: '#5F5F5F',        // 灰
    contrastText: '#FFFFFF',
  },
  // 状态色纸墨化降饱和（GUIDE 状态色语义表配套 token，批1 落值）
  success: {
    main: '#2F7D5B',
  },
  warning: {
    main: '#B07818',
  },
  error: {
    main: '#B3403A',
  },
  background: {
    default: '#F9F7F2',     // 纸白
    paper: '#FFFFFF',
    subtle: '#F3F0EA',      // 内嵌条目组底
  },
  text: {
    primary: '#1D1C1A',     // 墨黑
    secondary: '#5F5F5F',
  },
  divider: '#C7C2B9',
  mode: 'light' as PaletteMode,
};

/**
 * 冷灰配色方案 - 深色模式（v2 默认档：CODEX 系冷灰）
 */
const darkPalette = {
  primary: {
    main: '#4EC9A1',
    contrastText: '#000000',
    container: '#004D3A',
  },
  secondary: {
    main: '#9B9B9B',
    contrastText: '#000000',
  },
  // 状态色深色列微调适配冷底（GUIDE v2 状态色表，语义映射不变）
  success: {
    main: '#4EC98F',
  },
  warning: {
    main: '#D9A441',
  },
  error: {
    main: '#E5655E',
  },
  background: {
    default: '#0A0A0A',     // 冷黑
    paper: '#121212',
    subtle: '#1A1A1A',      // 内嵌条目组底
  },
  text: {
    primary: '#E8E8E8',
    secondary: '#9B9B9B',
  },
  divider: '#2A2A2A',
  mode: 'dark' as PaletteMode,
};

/**
 * 创建应用主题
 * @param mode - 主题模式（light/dark）
 */
export const createAppTheme = (mode: PaletteMode) => {
  const palette = mode === 'light' ? lightPalette : darkPalette;

  return createTheme({
    palette,
    shadows: noShadows,
    typography: {
      fontFamily: UI_FONT_STACK,
      // 针对阅读优化的字体大小
      body1: {
        fontSize: '16px',
        lineHeight: 1.75,
        letterSpacing: '0.02em',
      },
      h1: {
        fontSize: '2.5rem',
        fontWeight: 600,
      },
      h2: {
        fontSize: '2rem',
        fontWeight: 600,
      },
    },
    // 全局方角 2px（GUIDE v2「形体语言」节；v1 的 8px 作废）。
    shape: {
      borderRadius: 2,
    },
    components: {
      MuiButton: {
        styleOverrides: {
          root: {
            textTransform: 'none',
            borderRadius: '2px',
          },
        },
      },
      // 深色 Paper 的抬升叠影随 elevation 通道叠加，一并关掉。
      MuiPaper: {
        styleOverrides: {
          root: {
            backgroundImage: 'none',
          },
        },
      },
      // 浮层 = 实底 paper + 1px divider 细边框（GUIDE v2「形体语言」节）。
      MuiDialog: {
        styleOverrides: {
          paper: { border: `1px solid ${palette.divider}` },
        },
      },
      MuiMenu: {
        styleOverrides: {
          paper: { border: `1px solid ${palette.divider}` },
        },
      },
      MuiPopover: {
        styleOverrides: {
          paper: { border: `1px solid ${palette.divider}` },
        },
      },
      // 非 mono 场景数字兜底等宽对齐（GUIDE v2「字体系统」节）。
      MuiCssBaseline: {
        styleOverrides: {
          body: { fontVariantNumeric: 'tabular-nums' },
        },
      },
    },
  });
};
