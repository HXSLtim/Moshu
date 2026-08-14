'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '@/lib/api';
import type { Chapter } from '@/types';

export type ChapterSaveStatus = 'idle' | 'dirty' | 'saving' | 'saved' | 'error';
export type ChapterSaveReason = 'auto' | 'manual' | 'visibility';

export interface ChapterSaveSnapshot {
  chapterId: number;
  title: string;
  content: string;
  expectedVersion: number;
}

interface SavedBaseline {
  chapterId: number;
  title: string;
  content: string;
  version: number;
}

interface UseChapterSaveOptions {
  novelId: number;
  chapter: Chapter | null;
  title: string;
  content: string;
  autoSaveDelay?: number;
  onSaved?: (
    snapshot: ChapterSaveSnapshot,
    savedChapter: Chapter,
    savedAt: Date,
  ) => void;
  onError?: (message: string) => void;
}

interface UseChapterSaveReturn {
  status: ChapterSaveStatus;
  isDirty: boolean;
  isSaving: boolean;
  lastSavedAt: Date | null;
  error: string | null;
  saveNow: (reason?: ChapterSaveReason) => Promise<void>;
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError';
}

/**
 * 统一协调自动与手动保存：同一时刻只发送一个请求，过程中产生的新稿只保留最新版。
 */
export function useChapterSave({
  novelId,
  chapter,
  title,
  content,
  autoSaveDelay = 5000,
  onSaved,
  onError,
}: UseChapterSaveOptions): UseChapterSaveReturn {
  const [baseline, setBaseline] = useState<SavedBaseline | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [lastSavedAt, setLastSavedAt] = useState<Date | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const mountedRef = useRef(true);
  const generationRef = useRef(0);
  const versionRef = useRef(0);
  const baselineRef = useRef<SavedBaseline | null>(null);
  const latestRef = useRef({ chapterId: chapter?.id ?? null, title, content });
  const pendingRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const requestControllerRef = useRef<AbortController | null>(null);
  const inFlightRef = useRef<{
    generation: number;
    promise: Promise<void>;
  } | null>(null);
  const onSavedRef = useRef(onSaved);
  const onErrorRef = useRef(onError);

  latestRef.current = { chapterId: chapter?.id ?? null, title, content };
  onSavedRef.current = onSaved;
  onErrorRef.current = onError;

  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      clearTimer();
      generationRef.current += 1;
      requestControllerRef.current?.abort();
    };
  }, [clearTimer]);

  useEffect(() => {
    clearTimer();
    generationRef.current += 1;
    requestControllerRef.current?.abort();
    requestControllerRef.current = null;
    inFlightRef.current = null;
    pendingRef.current = false;
    setSaveError(null);
    setIsSaving(false);
    setLastSavedAt(null);

    if (!chapter) {
      baselineRef.current = null;
      versionRef.current = 0;
      setBaseline(null);
      return;
    }

    const initialBaseline: SavedBaseline = {
      chapterId: chapter.id,
      title: chapter.title,
      content: chapter.content,
      version: chapter.version ?? 0,
    };
    baselineRef.current = initialBaseline;
    versionRef.current = initialBaseline.version;
    setBaseline(initialBaseline);
    // 只在章节身份切换时建立基线；同章保存返回的新对象不能重置正在编辑的草稿。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chapter?.id, clearTimer, novelId]);

  const isDirty = useMemo(() => {
    if (!chapter || !baseline || baseline.chapterId !== chapter.id) return false;
    return title !== baseline.title || content !== baseline.content;
  }, [baseline, chapter, content, title]);

  const saveNow = useCallback(
    (reason: ChapterSaveReason = 'manual'): Promise<void> => {
      clearTimer();
      const generation = generationRef.current;
      const currentChapterId = latestRef.current.chapterId;

      if (!currentChapterId) return Promise.resolve();
      if (!latestRef.current.title.trim()) {
        const error = new Error('章节标题不能为空');
        if (reason === 'manual') {
          setSaveError(error.message);
          onErrorRef.current?.(error.message);
        }
        return Promise.reject(error);
      }

      pendingRef.current = true;
      setSaveError(null);

      const running = inFlightRef.current;
      if (running?.generation === generation) return running.promise;

      const drain = async () => {
        if (mountedRef.current) setIsSaving(true);

        while (pendingRef.current && generationRef.current === generation) {
          pendingRef.current = false;
          const latest = latestRef.current;
          const saved = baselineRef.current;

          if (!latest.chapterId || latest.chapterId !== currentChapterId) break;
          if (
            saved &&
            saved.chapterId === latest.chapterId &&
            saved.title === latest.title &&
            saved.content === latest.content
          ) {
            continue;
          }

          const expectedVersion = versionRef.current;
          const snapshot: ChapterSaveSnapshot = {
            chapterId: latest.chapterId,
            title: latest.title,
            content: latest.content,
            expectedVersion,
          };
          const controller = new AbortController();
          requestControllerRef.current = controller;

          try {
            const savedChapter = await api.updateChapter(
              novelId,
              snapshot.chapterId,
              {
                title: snapshot.title,
                content: snapshot.content,
                expected_version: snapshot.expectedVersion,
              },
              { signal: controller.signal },
            );

            if (generationRef.current !== generation) return;

            const savedAt = new Date();
            const nextVersion = savedChapter.version ?? expectedVersion + 1;
            const nextBaseline: SavedBaseline = {
              chapterId: snapshot.chapterId,
              title: snapshot.title,
              content: snapshot.content,
              version: nextVersion,
            };
            versionRef.current = nextVersion;
            baselineRef.current = nextBaseline;

            if (mountedRef.current) {
              setBaseline(nextBaseline);
              setLastSavedAt(savedAt);
              onSavedRef.current?.(snapshot, savedChapter, savedAt);
            }

            const newest = latestRef.current;
            if (
              newest.chapterId === snapshot.chapterId &&
              (newest.title !== snapshot.title || newest.content !== snapshot.content)
            ) {
              pendingRef.current = true;
            }
          } catch (error) {
            if (generationRef.current !== generation || isAbortError(error)) return;
            pendingRef.current = false;
            const message = error instanceof Error ? error.message : '保存失败';
            if (mountedRef.current) {
              setSaveError(message);
              onErrorRef.current?.(message);
            }
            throw error;
          } finally {
            if (requestControllerRef.current === controller) {
              requestControllerRef.current = null;
            }
          }
        }
      };

      const promise = drain().finally(() => {
        const active = inFlightRef.current;
        if (active?.generation === generation && active.promise === promise) {
          inFlightRef.current = null;
        }
        if (mountedRef.current && generationRef.current === generation) {
          setIsSaving(false);
        }
      });
      inFlightRef.current = { generation, promise };
      return promise;
    },
    [clearTimer, novelId],
  );

  useEffect(() => {
    clearTimer();
    if (!chapter || !isDirty || !title.trim() || isSaving) return;

    timerRef.current = setTimeout(() => {
      void saveNow('auto').catch(() => undefined);
    }, autoSaveDelay);
    return clearTimer;
  }, [
    autoSaveDelay,
    chapter,
    clearTimer,
    content,
    isDirty,
    isSaving,
    saveNow,
    title,
  ]);

  useEffect(() => {
    if (!isDirty) return;

    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    const handleVisibilityChange = () => {
      if (document.hidden) {
        void saveNow('visibility').catch(() => undefined);
      }
    };

    window.addEventListener('beforeunload', handleBeforeUnload);
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [isDirty, saveNow]);

  const status: ChapterSaveStatus = isSaving
    ? 'saving'
    : saveError
      ? 'error'
      : isDirty
        ? 'dirty'
        : lastSavedAt
          ? 'saved'
          : 'idle';

  return {
    status,
    isDirty,
    isSaving,
    lastSavedAt,
    error: saveError,
    saveNow,
  };
}
