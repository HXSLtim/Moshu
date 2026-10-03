import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  transpilePackages: ['@mui/material', '@mui/icons-material'],
  allowedDevOrigins: ['localhost', '127.0.0.1', '192.168.31.101'],
  // 桌面壳 P1：纯静态导出（前端零 SSR 面，已核 mutator/sse/路由树）；spike 构建走独立
  // distDir（NEXT_STATIC_BUILD=1），与 .next 隔离，不打坏运行中的 next dev。
  output: 'export',
  distDir: process.env.NEXT_STATIC_BUILD ? '.next-static' : '.next',
};

export default nextConfig;
