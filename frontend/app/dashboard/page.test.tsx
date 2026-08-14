import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '@/lib/api';
import type { Novel } from '@/types';
import DashboardPage from './page';

const navigation = vi.hoisted(() => ({
  router: {
    push: vi.fn(),
  },
}));

vi.mock('next/navigation', () => ({
  useRouter: () => navigation.router,
}));

const novel: Novel = {
  id: 1,
  title: '统计降级测试小说',
  genre: '测试',
  description: '验证统计接口不可用时仍能展示小说。',
  user_id: 1,
  created_at: '2026-07-10T00:00:00Z',
};

const localStorageMock: Storage = {
  length: 0,
  clear: vi.fn(),
  getItem: vi.fn(() => null),
  key: vi.fn(() => null),
  removeItem: vi.fn(),
  setItem: vi.fn(),
};

describe('DashboardPage 数据加载降级', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: localStorageMock,
    });
    navigation.router.push.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it('统计接口失败时仍展示小说且不跳转登录页', async () => {
    let rejectStatistics: (reason: Error) => void = () => undefined;
    vi.spyOn(api, 'getNovels').mockResolvedValue([novel]);
    vi.spyOn(api, 'getNovelStatistics').mockReturnValue(
      new Promise((_resolve, reject) => {
        rejectStatistics = reject;
      }),
    );

    render(<DashboardPage />);

    expect(await screen.findByText(novel.title)).toBeTruthy();
    rejectStatistics(new ApiError('统计接口暂未部署', 404));
    expect(
      await screen.findByText('统计数据暂不可用，小说列表和编辑功能不受影响'),
    ).toBeTruthy();
    expect(navigation.router.push).not.toHaveBeenCalled();
  });

  it('小说列表的非认证错误不会自动跳转登录页', async () => {
    vi.spyOn(api, 'getNovels').mockRejectedValue(
      new ApiError('小说服务暂不可用', 503),
    );
    vi.spyOn(api, 'getNovelStatistics').mockResolvedValue([]);

    render(<DashboardPage />);

    expect(await screen.findByText('小说服务暂不可用')).toBeTruthy();
    expect(navigation.router.push).not.toHaveBeenCalled();
  });
});
