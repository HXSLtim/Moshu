'use client';

import { useEffect, useRef } from 'react';

interface UseWorkspaceKeyboardShortcutsOptions {
  /** 弹窗、加载中或没有当前章节时禁用全部快捷键。 */
  enabled?: boolean;
  canUndo?: boolean;
  canRedo?: boolean;
  hasPreviousChapter?: boolean;
  hasNextChapter?: boolean;
  onSave: () => void | Promise<void>;
  onUndo?: () => void;
  onRedo?: () => void;
  onPreviousChapter?: () => void | Promise<void>;
  onNextChapter?: () => void | Promise<void>;
}

function hasPrimaryModifier(event: KeyboardEvent): boolean {
  return event.metaKey || event.ctrlKey;
}

/**
 * 工作台键盘快捷键。
 *
 * - 保存：⌘/Ctrl+S
 * - 撤销/重做：⌘/Ctrl+Z、⌘/Ctrl+Shift+Z 或 Ctrl+Y
 * - 章节切换：⌘/Ctrl+Alt+↑/↓
 *
 * IME 组合输入、浏览器默认行为和按键自动重复不会触发动作。
 */
export function useWorkspaceKeyboardShortcuts({
  enabled = true,
  canUndo = false,
  canRedo = false,
  hasPreviousChapter = false,
  hasNextChapter = false,
  onSave,
  onUndo,
  onRedo,
  onPreviousChapter,
  onNextChapter,
}: UseWorkspaceKeyboardShortcutsOptions): void {
  const optionsRef = useRef({
    enabled,
    canUndo,
    canRedo,
    hasPreviousChapter,
    hasNextChapter,
    onSave,
    onUndo,
    onRedo,
    onPreviousChapter,
    onNextChapter,
  });
  optionsRef.current = {
    enabled,
    canUndo,
    canRedo,
    hasPreviousChapter,
    hasNextChapter,
    onSave,
    onUndo,
    onRedo,
    onPreviousChapter,
    onNextChapter,
  };

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const current = optionsRef.current;
      if (
        !current.enabled ||
        event.defaultPrevented ||
        event.isComposing ||
        event.repeat
      ) {
        return;
      }

      const key = event.key.toLowerCase();
      const primary = hasPrimaryModifier(event);

      if (primary && key === 's') {
        event.preventDefault();
        void current.onSave();
        return;
      }

      const target = event.target;
      const editingOtherField = target instanceof HTMLElement &&
        (target.matches('input, textarea') || target.isContentEditable) &&
        !target.closest('[data-workspace-editor]');
      // 对话与设定输入框使用各自的原生撤销，不能误改正文。
      if (primary && (key === 'z' || key === 'y') && editingOtherField) return;

      if (primary && key === 'z') {
        // 正文是受控 TextField，统一阻止浏览器原生历史，避免绕过有界撤销栈。
        event.preventDefault();
        if (event.shiftKey && current.canRedo) {
          current.onRedo?.();
        } else if (!event.shiftKey && current.canUndo) {
          current.onUndo?.();
        }
        return;
      }

      if (primary && !event.shiftKey && key === 'y' && current.canRedo) {
        event.preventDefault();
        current.onRedo?.();
        return;
      }

      if (primary && event.altKey && key === 'arrowup') {
        if (current.hasPreviousChapter) {
          event.preventDefault();
          void current.onPreviousChapter?.();
        }
        return;
      }

      if (primary && event.altKey && key === 'arrowdown') {
        if (current.hasNextChapter) {
          event.preventDefault();
          void current.onNextChapter?.();
        }
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, []);
}
