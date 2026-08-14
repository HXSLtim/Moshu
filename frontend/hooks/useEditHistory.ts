'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

interface UseEditHistoryOptions {
  maxHistorySize?: number;
  maxCharacterBudget?: number;
  batchDelay?: number;
}

interface AddHistoryOptions {
  immediate?: boolean;
}

interface HistoryState {
  entries: string[];
  index: number;
}

interface UseEditHistoryReturn {
  history: string[];
  historyIndex: number;
  canUndo: boolean;
  canRedo: boolean;
  addToHistory: (content: string, options?: AddHistoryOptions) => void;
  flushHistory: () => void;
  undo: () => string | null;
  redo: () => string | null;
  clearHistory: (initialContent: string) => void;
}

const EMPTY_HISTORY: HistoryState = { entries: [], index: -1 };

/**
 * 按编辑批次保存正文快照，并同时限制条数与总字符量。
 */
export function useEditHistory(
  options: UseEditHistoryOptions = {},
): UseEditHistoryReturn {
  const {
    maxHistorySize = 50,
    maxCharacterBudget = 5_000_000,
    batchDelay = 400,
  } = options;
  const [state, setState] = useState<HistoryState>(EMPTY_HISTORY);
  const [hasPending, setHasPending] = useState(false);
  const stateRef = useRef<HistoryState>(EMPTY_HISTORY);
  const pendingContentRef = useRef<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const publish = useCallback((next: HistoryState) => {
    stateRef.current = next;
    setState(next);
  }, []);

  const commit = useCallback(
    (content: string) => {
      const current = stateRef.current;
      const entries = current.entries.slice(0, current.index + 1);
      if (entries[entries.length - 1] === content) return;

      entries.push(content);
      let totalCharacters = entries.reduce((total, item) => total + item.length, 0);

      while (
        entries.length > 1 &&
        (entries.length > maxHistorySize || totalCharacters > maxCharacterBudget)
      ) {
        totalCharacters -= entries[0].length;
        entries.shift();
      }

      publish({ entries, index: entries.length - 1 });
    },
    [maxCharacterBudget, maxHistorySize, publish],
  );

  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const flushHistory = useCallback(() => {
    clearTimer();
    const pending = pendingContentRef.current;
    pendingContentRef.current = null;
    setHasPending(false);
    if (pending !== null) commit(pending);
  }, [clearTimer, commit]);

  const addToHistory = useCallback(
    (content: string, addOptions: AddHistoryOptions = {}) => {
      pendingContentRef.current = content;
      setHasPending(true);
      clearTimer();

      if (addOptions.immediate) {
        flushHistory();
        return;
      }

      timerRef.current = setTimeout(flushHistory, batchDelay);
    },
    [batchDelay, clearTimer, flushHistory],
  );

  const undo = useCallback((): string | null => {
    flushHistory();
    const current = stateRef.current;
    if (current.index <= 0) return null;

    const next = { ...current, index: current.index - 1 };
    publish(next);
    return next.entries[next.index];
  }, [flushHistory, publish]);

  const redo = useCallback((): string | null => {
    flushHistory();
    const current = stateRef.current;
    if (current.index >= current.entries.length - 1) return null;

    const next = { ...current, index: current.index + 1 };
    publish(next);
    return next.entries[next.index];
  }, [flushHistory, publish]);

  const clearHistory = useCallback(
    (initialContent: string) => {
      clearTimer();
      pendingContentRef.current = null;
      setHasPending(false);
      publish({ entries: [initialContent], index: 0 });
    },
    [clearTimer, publish],
  );

  useEffect(
    () => () => {
      clearTimer();
    },
    [clearTimer],
  );

  return {
    history: state.entries,
    historyIndex: state.index,
    canUndo: state.index > 0 || hasPending,
    canRedo: state.index >= 0 && state.index < state.entries.length - 1,
    addToHistory,
    flushHistory,
    undo,
    redo,
    clearHistory,
  };
}

/**
 * 为仍在迁移中的调用方保留的瞬态标记 Hook。
 */
export function useIsApplyingHistoryRef() {
  return useRef(false);
}
