'use client';

import { createTheme, PaletteMode } from '@mui/material/styles';

// 扩展 token：内嵌卡/条目组的 subtle 底色（GUIDE「扩展 token」节，批1 落值）。
declare module '@mui/material/styles' {
  interface TypeBackground {
    subtle: string;
  }
}

/**
 * 纸墨配色方案 - 浅色模式
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
    primary: '#1D1C1A',     // 墨黑 (87% opacity)
    secondary: '#5F5F5F',
  },
  divider: '#C7C2B9',
  mode: 'light' as PaletteMode,
};

/**
 * 纸墨配色方案 - 深色模式
 */
const darkPalette = {
  primary: {
    main: '#4EC9A1',        // 降低亮度的绿
    contrastText: '#000000',
    container: '#004D3A',
  },
  secondary: {
    main: '#9E9E9E',
    contrastText: '#000000',
  },
  success: {
    main: '#5FC9A6',
  },
  warning: {
    main: '#D9A441',
  },
  error: {
    main: '#E57368',
  },
  background: {
    default: '#1B1B1B',     // 纯黑5%上浮
    paper: '#242424',
    subtle: '#2B2B28',      // 内嵌条目组底
  },
  text: {
    primary: '#E2E0DB',     // 米白 (93% white)
    secondary: '#9E9E9E',
  },
  divider: '#494944',
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
    typography: {
      fontFamily: [
        '-apple-system',
        'BlinkMacSystemFont',
        '"Segoe UI"',
        'Roboto',
        '"Noto Sans SC"',
        'sans-serif',
      ].join(','),
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
    shape: {
      borderRadius: 8,
    },
    components: {
      MuiButton: {
        styleOverrides: {
          root: {
            textTransform: 'none',
            borderRadius: '8px',
          },
        },
      },
      MuiCard: {
        styleOverrides: {
          root: {
            boxShadow: mode === 'light'
              ? '0 2px 8px rgba(0,0,0,0.08)'
              : '0 2px 8px rgba(0,0,0,0.3)',
          },
        },
      },
    },
  });
};
