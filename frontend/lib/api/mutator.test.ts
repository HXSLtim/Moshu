import { afterEach, describe, expect, it } from 'vitest';
import { resolveApiBase, resolveApiUrl } from './mutator';

const win = window as typeof window & { __NAI_API_BASE__?: string };

describe('API 基址解析(壳 P1 件5 运行时覆盖点)', () => {
  afterEach(() => {
    delete win.__NAI_API_BASE__;
    delete process.env.NEXT_PUBLIC_API_BASE;
  });

  it('无壳注入无 env 时用本地缺省', () => {
    delete win.__NAI_API_BASE__;
    delete process.env.NEXT_PUBLIC_API_BASE;
    expect(resolveApiBase()).toBe('http://127.0.0.1:8000/api');
  });

  it('解析序=壳注入>构建期 env>缺省', () => {
    process.env.NEXT_PUBLIC_API_BASE = 'http://build-time-host:9000/api';
    expect(resolveApiBase()).toBe('http://build-time-host:9000/api');

    win.__NAI_API_BASE__ = 'http://127.0.0.1:37421/api';
    expect(resolveApiBase()).toBe('http://127.0.0.1:37421/api');
  });

  it('resolveApiUrl 按当次基址解析三形态路径', () => {
    process.env.NEXT_PUBLIC_API_BASE = 'http://build-time-host:9000/api';
    win.__NAI_API_BASE__ = 'http://127.0.0.1:37421/api';

    expect(resolveApiUrl('/api/health')).toBe('http://127.0.0.1:37421/api/health');
    expect(resolveApiUrl('/novels/1')).toBe('http://127.0.0.1:37421/api/novels/1');
    expect(resolveApiUrl('http://elsewhere.example/x')).toBe('http://elsewhere.example/x');
  });
});
