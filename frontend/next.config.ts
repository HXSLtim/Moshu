import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  transpilePackages: ['@mui/material', '@mui/icons-material'],
  allowedDevOrigins: ['localhost', '127.0.0.1', '192.168.31.101'],
};

export default nextConfig;
