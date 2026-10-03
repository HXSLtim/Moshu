'use client';

import { useMemo } from 'react';
import { ThemeProvider } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';
import { ColorModeProvider, useColorMode } from '@/hooks/useColorMode';
import { createAppTheme } from '@/theme/theme';

function ThemedLayout({ children }: { children: React.ReactNode }) {
  const { mode } = useColorMode();
  const theme = useMemo(() => createAppTheme(mode), [mode]);

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      {/* 产品名进浏览器标签页（React 19 将 title 提升至 head；根布局为 client 组件，不走 metadata 导出）。 */}
      <title>墨枢</title>
      {children}
    </ThemeProvider>
  );
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body>
        <ColorModeProvider>
          <ThemedLayout>{children}</ThemedLayout>
        </ColorModeProvider>
      </body>
    </html>
  );
}
