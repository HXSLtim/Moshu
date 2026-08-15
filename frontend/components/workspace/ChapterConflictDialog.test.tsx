import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Chapter } from '@/types';
import type { ChapterSaveConflict } from '@/hooks/useChapterSave';
import ChapterConflictDialog from './ChapterConflictDialog';

const conflict: ChapterSaveConflict = {
  snapshot: {
    chapterId: 10,
    title: '我的标题',
    content: '本地草稿内容',
    expectedVersion: 3,
  },
  serverVersion: 5,
  message: '章节已被其他保存更新，当前版本为5，请刷新后重试',
};

const serverChapter: Chapter = {
  id: 10,
  novel_id: 1,
  chapter_number: 1,
  title: '服务端标题',
  content: '服务端更新后的内容',
  word_count: 9,
  version: 5,
  created_at: '2026-07-10T00:00:00Z',
  updated_at: '2026-07-10T00:01:00Z',
};

describe('ChapterConflictDialog', () => {
  afterEach(() => cleanup());

  it('并排展示本地版本与服务端版本，三个动作分别触发回调', () => {
    const onAcceptServer = vi.fn();
    const onOverwriteServer = vi.fn();
    const onCopyToNewChapter = vi.fn();
    const onClose = vi.fn();

    render(
      <ChapterConflictDialog
        open
        conflict={conflict}
        serverChapter={serverChapter}
        loadingServer={false}
        actionLoading={null}
        onAcceptServer={onAcceptServer}
        onOverwriteServer={onOverwriteServer}
        onCopyToNewChapter={onCopyToNewChapter}
        onClose={onClose}
      />,
    );

    expect(screen.getByText('我的版本：我的标题')).toBeTruthy();
    expect(screen.getByText('服务端版本：服务端标题')).toBeTruthy();
    expect(screen.getByDisplayValue('本地草稿内容')).toBeTruthy();
    expect(screen.getByDisplayValue('服务端更新后的内容')).toBeTruthy();

    screen.getByRole('button', { name: '放弃我的版本' }).click();
    screen.getByRole('button', { name: '另存为新章节' }).click();
    screen.getByRole('button', { name: '用我的版本覆盖' }).click();
    screen.getByRole('button', { name: '关闭' }).click();

    expect(onAcceptServer).toHaveBeenCalledTimes(1);
    expect(onCopyToNewChapter).toHaveBeenCalledTimes(1);
    expect(onOverwriteServer).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('服务端版本尚未加载时禁止覆盖与放弃，但允许另存', () => {
    render(
      <ChapterConflictDialog
        open
        conflict={conflict}
        serverChapter={null}
        loadingServer
        actionLoading={null}
        onAcceptServer={vi.fn()}
        onOverwriteServer={vi.fn()}
        onCopyToNewChapter={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(
      (screen.getByRole('button', { name: '放弃我的版本' }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(
      (screen.getByRole('button', { name: '用我的版本覆盖' }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(
      (screen.getByRole('button', { name: '另存为新章节' }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
  });
});
