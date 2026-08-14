'use client';

import { useState, useEffect, useCallback } from 'react';
import { api } from '@/lib/api';
import type { Novel, Chapter, ChapterSummary } from '@/types';

interface UseWorkspaceOptions {
  novelId: number;
  chapterId?: number;
}

interface UseWorkspaceReturn {
  // 数据
  novel: Novel | null;
  chapters: ChapterSummary[];
  currentChapter: Chapter | null;
  // 内容
  title: string;
  content: string;
  // 保存状态
  autoSaving: boolean;
  lastSavedAt: Date | null;
  lastSavedTitle: string;
  lastSavedContent: string;
  // UI状态
  loading: boolean;
  error: string;
  // 操作方法
  loadWorkspace: () => Promise<void>;
  saveChapter: (title: string, content: string) => Promise<void>;
  setTitle: (title: string) => void;
  setContent: (content: string) => void;
}

/**
 * 工作区数据管理Hook
 * 封装工作区的数据加载、保存等核心业务逻辑
 */
export function useWorkspace({ novelId, chapterId }: UseWorkspaceOptions): UseWorkspaceReturn {
  // 数据状态
  const [novel, setNovel] = useState<Novel | null>(null);
  const [chapters, setChapters] = useState<ChapterSummary[]>([]);
  const [currentChapter, setCurrentChapter] = useState<Chapter | null>(null);

  // 内容状态
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');

  // 保存状态
  const autoSaving = false;
  const [lastSavedAt, setLastSavedAt] = useState<Date | null>(null);
  const [lastSavedTitle, setLastSavedTitle] = useState('');
  const [lastSavedContent, setLastSavedContent] = useState('');

  // UI状态
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  /**
   * 加载工作台数据
   */
  const loadWorkspace = useCallback(async () => {
    if (!novelId) return;

    try {
      setLoading(true);
      setError('');

      const [novelData, chaptersData, chapterData] = await Promise.all([
        api.getNovel(novelId),
        api.getAllChapterSummaries(novelId),
        chapterId ? api.getChapter(novelId, chapterId) : Promise.resolve(null),
      ]);

      setNovel(novelData);
      setChapters(chaptersData.sort((a, b) => a.chapter_number - b.chapter_number));

      // 加载当前章节
      if (chapterData) {
          setCurrentChapter(chapterData);
          setContent(chapterData.content);
          setTitle(chapterData.title);
          setLastSavedTitle(chapterData.title);
          setLastSavedContent(chapterData.content);
          setLastSavedAt(null);
      }
    } catch {
      setError('加载失败，请返回重试');
    } finally {
      setLoading(false);
    }
  }, [novelId, chapterId]);

  /**
   * 保存章节
   */
  const saveChapter = useCallback(async (saveTitle: string, saveContent: string) => {
    if (!currentChapter) {
      throw new Error('未选择章节');
    }

    if (!saveTitle || !saveContent) {
      throw new Error('标题和内容不能为空');
    }

    try {
      const savedChapter = await api.updateChapter(novelId, currentChapter.id, {
        title: saveTitle,
        content: saveContent,
        expected_version: currentChapter.version,
      });

      setCurrentChapter(savedChapter);
      setLastSavedAt(new Date());
      setLastSavedTitle(saveTitle);
      setLastSavedContent(saveContent);
      setError('');
    } catch (err) {
      throw new Error(err instanceof Error ? err.message : '保存失败');
    }
  }, [novelId, currentChapter]);

  // 监听URL变化重新加载数据
  useEffect(() => {
    if (novelId) {
      loadWorkspace();
    }
  }, [novelId, chapterId, loadWorkspace]);

  return {
    // 数据
    novel,
    chapters,
    currentChapter,
    // 内容
    title,
    content,
    // 保存状态
    autoSaving,
    lastSavedAt,
    lastSavedTitle,
    lastSavedContent,
    // UI状态
    loading,
    error,
    // 操作方法
    loadWorkspace,
    saveChapter,
    setTitle,
    setContent,
  };
}

/**
 * 判断是否有未保存的更改
 */
export function hasUnsavedChanges(
  title: string,
  content: string,
  lastSavedTitle: string,
  lastSavedContent: string
): boolean {
  return title !== lastSavedTitle || content !== lastSavedContent;
}

/**
 * 格式化时间（HH:MM）
 */
export function formatTime(date: Date): string {
  const hours = date.getHours().toString().padStart(2, '0');
  const minutes = date.getMinutes().toString().padStart(2, '0');
  return `${hours}:${minutes}`;
}
