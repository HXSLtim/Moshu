'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '@/lib/api';
import type { Chapter } from '@/types';

export type ChapterSaveStatus =
  | 'idle'
  | 'dirty'
  | 'saving'
  | 'saved'
  | 'error'
  | 'offline';
export type ChapterSaveReason = 'auto' | 'manual' | 'visibility';

export interface ChapterSaveSnapshot {
  chapterId: number;
  title: string;
  content: string;
  expectedVersion: number;
}

export interface ChapterDraftBackup {
  novelId: number;
  chapterId: number;
  title: string;
  content: string;
  version: number;
  savedAt: string;
}

export interface ChapterSaveConflict {
  snapshot: ChapterSaveSnapshot;
  serverVersion: number;
  message: string;
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
  onConflict?: (conflict: ChapterSaveConflict) => void;
  onDraftRestored?: (draft: ChapterDraftBackup) => void;
}

interface UseChapterSaveReturn {
  status: ChapterSaveStatus;
  isDirty: boolean;
  isSaving: boolean;
  lastSavedAt: Date | null;
  error: string | null;
  conflict: ChapterSaveConflict | null;
  isOffline: boolean;
  hasLocalBackup: boolean;
  saveNow: (reason?: ChapterSaveReason) => Promise<void>;
  clearConflict: () => void;
  overwriteConflict: (serverVersion?: number) => Promise<void>;
  adoptServerChapter: (serverChapter: Chapter) => void;
}

const DRAFT_KEY_PREFIX = 'nai_chapter_draft_';
const BACKUP_DELAY = 600;

function draftKey(novelId: number, chapterId: number): string {
  return `${DRAFT_KEY_PREFIX}${novelId}_${chapterId}`;
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError';
}

function readDraft(novelId: number, chapterId: number): ChapterDraftBackup | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(draftKey(novelId, chapterId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<ChapterDraftBackup>;
    if (
      parsed.novelId !== novelId ||
      parsed.chapterId !== chapterId ||
      typeof parsed.title !== 'string' ||
      typeof parsed.content !== 'string' ||
      typeof parsed.version !== 'number' ||
      typeof parsed.savedAt !== 'string'
    ) {
      return null;
    }
    return parsed as ChapterDraftBackup;
  } catch {
    return null;
  }
}

function writeDraft(
  novelId: number,
  snapshot: ChapterSaveSnapshot,
  version: number,
): void {
  if (typeof window === 'undefined') return;
  try {
    const draft: ChapterDraftBackup = {
      novelId,
      chapterId: snapshot.chapterId,
      title: snapshot.title,
      content: snapshot.content,
      version,
      savedAt: new Date().toISOString(),
    };
    window.localStorage.setItem(
      draftKey(novelId, snapshot.chapterId),
      JSON.stringify(draft),
    );
  } catch {
    // 隐私模式或容量不足时放弃备份，不阻断正文编辑。
  }
}

function removeDraft(novelId: number, chapterId: number): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.removeItem(draftKey(novelId, chapterId));
  } catch {
    // 忽略清理失败。
  }
}

function isDraftNewerThanServer(
  draft: ChapterDraftBackup,
  chapter: Chapter,
): boolean {
  const draftTime = Date.parse(draft.savedAt);
  if (!Number.isFinite(draftTime)) return false;
  if (!chapter.updated_at) return true;
  const serverTime = Date.parse(chapter.updated_at);
  return !Number.isFinite(serverTime) || draftTime > serverTime;
}

function getErrorStatus(error: unknown): number | null {
  if (!error || typeof error !== 'object') return null;
  if ('status' in error && typeof error.status === 'number') return error.status;
  return null;
}

function parseServerVersion(message: string): number | null {
  const match = message.match(/当前版本(?:为|:)?\s*(\d+)/);
  if (!match) return null;
  const version = Number(match[1]);
  return Number.isInteger(version) && version > 0 ? version : null;
}

function isBrowserOnline(): boolean {
  return typeof navigator === 'undefined' || navigator.onLine !== false;
}

/**
 * 统一协调自动与手动保存：同一时刻只发送一个请求，过程中产生的新稿只保留最新版。
 *
 * 409 时冻结自动保存并暴露冲突详情；断网期间写本地草稿，恢复连接后自动重放。
 */
export function useChapterSave({
  novelId,
  chapter,
  title,
  content,
  autoSaveDelay = 5000,
  onSaved,
  onError,
  onConflict,
  onDraftRestored,
}: UseChapterSaveOptions): UseChapterSaveReturn {
  const [baseline, setBaseline] = useState<SavedBaseline | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [lastSavedAt, setLastSavedAt] = useState<Date | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<ChapterSaveConflict | null>(null);
  const [isOffline, setIsOffline] = useState(!isBrowserOnline());
  const [hasLocalBackup, setHasLocalBackup] = useState(false);

  const mountedRef = useRef(true);
  const generationRef = useRef(0);
  const versionRef = useRef(0);
  const baselineRef = useRef<SavedBaseline | null>(null);
  const latestRef = useRef({ chapterId: chapter?.id ?? null, title, content });
  const pendingRef = useRef(false);
  const conflictRef = useRef<ChapterSaveConflict | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const backupTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const requestControllerRef = useRef<AbortController | null>(null);
  const inFlightRef = useRef<{
    generation: number;
    promise: Promise<void>;
  } | null>(null);
  const onSavedRef = useRef(onSaved);
  const onErrorRef = useRef(onError);
  const onConflictRef = useRef(onConflict);
  const onDraftRestoredRef = useRef(onDraftRestored);

  latestRef.current = { chapterId: chapter?.id ?? null, title, content };
  onSavedRef.current = onSaved;
  onErrorRef.current = onError;
  onConflictRef.current = onConflict;
  onDraftRestoredRef.current = onDraftRestored;

  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const clearBackupTimer = useCallback(() => {
    if (backupTimerRef.current) {
      clearTimeout(backupTimerRef.current);
      backupTimerRef.current = null;
    }
  }, []);

  const clearConflictState = useCallback(() => {
    conflictRef.current = null;
    setConflict(null);
    setSaveError(null);
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      clearTimer();
      clearBackupTimer();
      generationRef.current += 1;
      requestControllerRef.current?.abort();
    };
  }, [clearBackupTimer, clearTimer]);

  useEffect(() => {
    clearTimer();
    clearBackupTimer();
    generationRef.current += 1;
    requestControllerRef.current?.abort();
    requestControllerRef.current = null;
    inFlightRef.current = null;
    pendingRef.current = false;
    setSaveError(null);
    setConflict(null);
    conflictRef.current = null;
    setIsSaving(false);
    setLastSavedAt(null);

    if (!chapter) {
      baselineRef.current = null;
      versionRef.current = 0;
      setBaseline(null);
      return;
    }

    const draft = readDraft(novelId, chapter.id);
    if (
      draft &&
      (draft.title !== chapter.title || draft.content !== chapter.content) &&
      isDraftNewerThanServer(draft, chapter)
    ) {
      onDraftRestoredRef.current?.(draft);
    } else if (draft) {
      removeDraft(novelId, chapter.id);
      setHasLocalBackup(false);
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
  }, [chapter?.id, clearBackupTimer, clearTimer, novelId]);

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
      if (conflictRef.current) {
        return Promise.reject(
          new Error(conflictRef.current.message || '章节版本冲突，请先处理'),
        );
      }
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
            removeDraft(novelId, snapshot.chapterId);

            if (mountedRef.current) {
              setBaseline(nextBaseline);
              setLastSavedAt(savedAt);
              setHasLocalBackup(false);
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
            const status = getErrorStatus(error);

            if (status === 409) {
              const message = error instanceof Error ? error.message : '章节版本冲突';
              const conflictState: ChapterSaveConflict = {
                snapshot,
                serverVersion: parseServerVersion(message) ?? expectedVersion + 1,
                message,
              };
              conflictRef.current = conflictState;
              if (mountedRef.current) {
                setConflict(conflictState);
                setSaveError(message);
                onConflictRef.current?.(conflictState);
              }
              throw error;
            }

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

  const overwriteConflict = useCallback(
    async (serverVersion?: number): Promise<void> => {
      const currentConflict = conflictRef.current;
      if (!currentConflict) return;
      const nextVersion =
        serverVersion && Number.isInteger(serverVersion) && serverVersion > 0
          ? serverVersion
          : currentConflict.serverVersion;
      clearConflictState();
      versionRef.current = nextVersion;
      pendingRef.current = true;
      await saveNow('manual');
    },
    [clearConflictState, saveNow],
  );

  const adoptServerChapter = useCallback(
    (serverChapter: Chapter) => {
      const currentChapterId = latestRef.current.chapterId;
      if (!serverChapter || serverChapter.id !== currentChapterId) return;

      const nextBaseline: SavedBaseline = {
        chapterId: serverChapter.id,
        title: serverChapter.title,
        content: serverChapter.content,
        version: serverChapter.version ?? 0,
      };
      baselineRef.current = nextBaseline;
      versionRef.current = nextBaseline.version;
      clearConflictState();
      if (mountedRef.current) {
        setBaseline(nextBaseline);
        setLastSavedAt(null);
      }
    },
    [clearConflictState],
  );

  useEffect(() => {
    clearTimer();
    if (
      !chapter ||
      !isDirty ||
      !title.trim() ||
      isSaving ||
      conflict ||
      isOffline
    ) {
      return;
    }

    timerRef.current = setTimeout(() => {
      void saveNow('auto').catch(() => undefined);
    }, autoSaveDelay);
    return clearTimer;
  }, [
    autoSaveDelay,
    chapter,
    clearTimer,
    conflict,
    content,
    isDirty,
    isOffline,
    isSaving,
    saveError,
    saveNow,
    title,
  ]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const updateOffline = () => setIsOffline(!navigator.onLine);

    const handleOffline = () => {
      updateOffline();
      clearTimer();
      requestControllerRef.current?.abort();
    };
    const handleOnline = () => {
      updateOffline();
      if (isDirty && !conflict) {
        void saveNow('auto').catch(() => undefined);
      }
    };

    window.addEventListener('offline', handleOffline);
    window.addEventListener('online', handleOnline);
    return () => {
      window.removeEventListener('offline', handleOffline);
      window.removeEventListener('online', handleOnline);
    };
  }, [clearTimer, conflict, isDirty, saveNow]);

  useEffect(() => {
    clearBackupTimer();
    if (!chapter || !isDirty) {
      return;
    }

    backupTimerRef.current = setTimeout(() => {
      const latest = latestRef.current;
      if (!latest.chapterId) return;
      writeDraft(
        novelId,
        {
          chapterId: latest.chapterId,
          title: latest.title,
          content: latest.content,
          expectedVersion: versionRef.current,
        },
        versionRef.current,
      );
      if (mountedRef.current) setHasLocalBackup(true);
    }, BACKUP_DELAY);
    return clearBackupTimer;
  }, [chapter, clearBackupTimer, content, isDirty, novelId, title]);

  useEffect(() => {
    if (!isDirty) return;

    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      const latest = latestRef.current;
      if (latest.chapterId) {
        writeDraft(
          novelId,
          {
            chapterId: latest.chapterId,
            title: latest.title,
            content: latest.content,
            expectedVersion: versionRef.current,
          },
          versionRef.current,
        );
      }
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
  }, [isDirty, novelId, saveNow]);

  const status: ChapterSaveStatus = isSaving
    ? 'saving'
    : conflict
      ? 'error'
      : saveError
        ? 'error'
        : isOffline && isDirty
          ? 'offline'
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
    conflict,
    isOffline,
    hasLocalBackup,
    saveNow,
    clearConflict: clearConflictState,
    overwriteConflict,
    adoptServerChapter,
  };
}
