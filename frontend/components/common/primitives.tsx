'use client';

import type { ReactNode } from 'react';
import { Alert, Box, Chip, Divider, Typography } from '@mui/material';

/**
 * 共享原语三件套（角色管理分支先带，统一批次收编平移）。
 * API 依据 UI_DESIGN_GUIDELINES「共享原语」节，非私设风格；收编只挪位置不改行为。
 */

/** 区块头：subtitle2/700 + 可选右侧动作槽 + 可选分隔线。 */
export function SectionHeader({ title, action, divider = true }: { title: string; action?: ReactNode; divider?: boolean }) {
  return <>
    <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 1 }}>
      <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>{title}</Typography>
      {action}
    </Box>
    {divider && <Divider sx={{ my: 1 }} />}
  </>;
}

/** 空态/单行状态说明：「还没有 X」+ 一句引导 + 可选动作槽；禁占位假数据。 */
export function EmptyState({ title, hint, action, severity = 'info' }: { title: string; hint?: string; action?: ReactNode; severity?: 'info' | 'warning' }) {
  return <Alert severity={severity} action={action}>
    <Typography variant="body2">{title}</Typography>
    {hint && <Typography variant="body2" color="text.secondary">{hint}</Typography>}
  </Alert>;
}

type StatusTone = 'pending' | 'success' | 'achieved' | 'rejected' | 'stale' | 'error' | 'planned' | 'neutral';

/** tone → 状态色语义表；实心=当下状态，描边=属性标签/历史既成。neutral 与 rejected/planned 同为 default 灰描边，语义分工是非状态的属性标签（如重要程度）。 */
const toneStyles: Record<StatusTone, { color: 'success' | 'warning' | 'error' | 'default'; filled: boolean }> = {
  pending: { color: 'default', filled: true },
  success: { color: 'success', filled: true },
  achieved: { color: 'success', filled: false },
  rejected: { color: 'default', filled: false },
  stale: { color: 'warning', filled: false },
  error: { color: 'error', filled: true },
  planned: { color: 'default', filled: false },
  neutral: { color: 'default', filled: false },
};

/** 状态章：tone 只取语义表色阶，尺寸两档（small 元信息标签 / medium 状态章），无随手 height/字号。 */
export function StatusChip({ tone, label, size = 'medium' }: { tone: StatusTone; label: string; size?: 'small' | 'medium' }) {
  const style = toneStyles[tone];
  return <Chip size={size} label={label} color={style.color} variant={style.filled ? 'filled' : 'outlined'} />;
}
