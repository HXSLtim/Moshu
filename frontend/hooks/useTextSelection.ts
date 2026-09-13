'use client';

import { useState, useCallback, useRef } from 'react';

interface UseTextSelectionReturn {
  // 选择状态
  selectionStart: number | null;
  selectionEnd: number | null;
  selectedText: string;
  // 操作方法
  handleTextSelection: (event: React.SyntheticEvent) => void;
  clearSelection: () => void;
  // 输入框ref
  contentInputRef: React.RefObject<HTMLTextAreaElement | null>;
  // 是否选中了文本
  hasSelection: boolean;
}

/**
 * 文本选择管理Hook
 * 用于管理工作区中文本选择状态
 */
export function useTextSelection(): UseTextSelectionReturn {
  // 局部改写状态
  const [selectionStart, setSelectionStart] = useState<number | null>(null);
  const [selectionEnd, setSelectionEnd] = useState<number | null>(null);
  const [selectedText, setSelectedText] = useState('');

  // 内容输入框ref
  const contentInputRef = useRef<HTMLTextAreaElement | null>(null);

  /**
   * 处理文本选择
   */
  const handleTextSelection = useCallback(
    (event: React.SyntheticEvent) => {
      if (!(event.target instanceof HTMLTextAreaElement)) return;
      const target = event.target;
      const start = target.selectionStart;
      const end = target.selectionEnd;

      if (start !== end) {
        setSelectionStart(start);
        setSelectionEnd(end);
        setSelectedText(target.value.slice(start, end));
      } else {
        setSelectionStart(null);
        setSelectionEnd(null);
        setSelectedText('');
      }
    },
    []
  );

  /**
   * 清除选择
   */
  const clearSelection = useCallback(() => {
    setSelectionStart(null);
    setSelectionEnd(null);
    setSelectedText('');
  }, []);

  // 是否选中了文本
  const hasSelection = selectionStart !== null && selectionEnd !== null && selectionStart !== selectionEnd;

  return {
    selectionStart,
    selectionEnd,
    selectedText,
    handleTextSelection,
    clearSelection,
    contentInputRef,
    hasSelection,
  };
}
