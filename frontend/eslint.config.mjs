import { FlatCompat } from '@eslint/eslintrc';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const currentFile = fileURLToPath(import.meta.url);
const currentDirectory = path.dirname(currentFile);
const compat = new FlatCompat({ baseDirectory: currentDirectory });

const config = [
  {
    ignores: ['.next/**', 'node_modules/**', 'tsconfig.tsbuildinfo', 'next-env.d.ts'],
  },
  ...compat.extends('next/core-web-vitals', 'next/typescript'),
  {
    rules: {
      // 现有 API 事件载荷仍在逐步收敛，先保持兼容，不让存量 any 阻断验证。
      '@typescript-eslint/no-explicit-any': 'off',
      // 小说文案包含大量中文引号，JSX 中不强制改写为实体。
      'react/no-unescaped-entities': 'off',
    },
  },
];

export default config;
