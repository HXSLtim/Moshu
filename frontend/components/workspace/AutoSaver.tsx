'use client';

import { Chip } from '@mui/material';
import type { ChapterSaveStatus } from '@/hooks/useChapterSave';

interface AutoSaverProps {
  status: ChapterSaveStatus;
  lastSavedAt: Date | null;
}

function formatTime(date: Date): string {
  return date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

/**
 * 保存状态只负责展示，保存队列统一由 useChapterSave 管理。
 */
export default function AutoSaver({ status, lastSavedAt }: AutoSaverProps) {
  if (status === 'idle') return null;

  if (status === 'saving') {
    return (
      <Chip
        label="保存中..."
        size="small"
        color="info"
        aria-live="polite"
        sx={{
          animation: 'pulse 2s infinite',
          '@keyframes pulse': {
            '0%': { opacity: 1 },
            '50%': { opacity: 0.5 },
            '100%': { opacity: 1 },
          },
        }}
      />
    );
  }

  if (status === 'error') {
    return <Chip label="保存失败" size="small" color="error" aria-live="assertive" />;
  }

  if (status === 'dirty') {
    return <Chip label="未保存" size="small" color="warning" aria-live="polite" />;
  }

  return (
    <Chip
      label={lastSavedAt ? `${formatTime(lastSavedAt)} 已保存` : '已保存'}
      size="small"
      color="success"
      variant="outlined"
      aria-live="polite"
    />
  );
}
