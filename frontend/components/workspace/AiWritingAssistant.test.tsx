import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/lib/api';
import AiWritingAssistant from './AiWritingAssistant';

describe('AiWritingAssistant 应用到下一章', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  beforeEach(() => {
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      callback(0);
      return 1;
    });
    vi.stubGlobal('cancelAnimationFrame', vi.fn());
    vi.spyOn(api, 'continueChapterStream').mockImplementation(
      async (_data, callbacks) => {
        callbacks.onChunk('需要保留的生成稿');
        callbacks.onDone?.();
      },
    );
  });

  it('父级创建失败时保留生成稿供重试', async () => {
    const applyToNext = vi.fn().mockRejectedValue(new Error('创建失败'));
    const onError = vi.fn();
    render(
      <AiWritingAssistant
        novelId={1}
        chapterId={2}
        currentContent="当前正文"
        onContentGenerated={vi.fn()}
        onError={onError}
        onApplyToNextChapter={applyToNext}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'AI续写' }));
    expect(await screen.findByText('需要保留的生成稿')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '应用到下一章节' }));

    await waitFor(() => expect(onError).toHaveBeenCalledWith('创建失败'));
    expect(screen.getByText('需要保留的生成稿')).toBeTruthy();
    expect(screen.getByRole('button', { name: '应用到下一章节' })).toBeTruthy();
  });

  it('父级创建成功后才清空生成稿', async () => {
    const applyToNext = vi.fn().mockResolvedValue(undefined);
    render(
      <AiWritingAssistant
        novelId={1}
        chapterId={2}
        currentContent="当前正文"
        onContentGenerated={vi.fn()}
        onError={vi.fn()}
        onApplyToNextChapter={applyToNext}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'AI续写' }));
    expect(await screen.findByText('需要保留的生成稿')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '应用到下一章节' }));

    await waitFor(() => expect(applyToNext).toHaveBeenCalledWith('需要保留的生成稿'));
    await waitFor(() => expect(screen.queryByText('需要保留的生成稿')).toBeNull());
  });

  it('一致性重试耗尽时明确标记冲突稿', async () => {
    vi.mocked(api.continueChapterStream).mockImplementationOnce(
      async (_data, callbacks) => {
        callbacks.onChunk('仍有冲突的生成稿');
        callbacks.onMetadata?.({
          retry_count: 2,
          final_consistency: {
            status: 'conflict_after_retries',
            has_conflict: true,
            retry_exhausted: true,
            is_complete: false,
            checks_skipped: ['knowledge_graph'],
            violations: ['人物年龄与前文设定不一致'],
          },
        });
        callbacks.onDone?.();
      },
    );

    render(
      <AiWritingAssistant
        novelId={1}
        chapterId={2}
        currentContent="当前正文"
        onContentGenerated={vi.fn()}
        onError={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'AI续写' }));

    expect(
      await screen.findByText('一致性检查重试已耗尽，当前仍是冲突稿'),
    ).toBeTruthy();
    expect(screen.getByText('部分一致性检查未执行')).toBeTruthy();
    expect(screen.getByText('未执行：知识图谱')).toBeTruthy();
    expect(screen.getByText('· 人物年龄与前文设定不一致')).toBeTruthy();
  });

  it('无冲突但检查不完整时显示独立警告', async () => {
    vi.mocked(api.continueChapterStream).mockImplementationOnce(
      async (_data, callbacks) => {
        callbacks.onChunk('检查不完整的生成稿');
        callbacks.onMetadata?.({
          retry_count: 0,
          final_consistency: {
            status: 'incomplete',
            has_conflict: false,
            retry_exhausted: false,
            is_complete: false,
            checks_skipped: ['knowledge_graph', 'emotion_state', 'custom_guard'],
            violations: [],
          },
        });
        callbacks.onDone?.();
      },
    );

    render(
      <AiWritingAssistant
        novelId={1}
        chapterId={2}
        currentContent="当前正文"
        onContentGenerated={vi.fn()}
        onError={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'AI续写' }));

    expect(await screen.findByText('部分一致性检查未执行')).toBeTruthy();
    expect(
      screen.getByText('未执行：知识图谱、情绪状态、custom_guard'),
    ).toBeTruthy();
    expect(screen.queryByText('当前生成稿存在一致性冲突')).toBeNull();
  });
});
