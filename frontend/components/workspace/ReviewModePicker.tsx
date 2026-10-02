'use client';

import { Box, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material';
import { alpha } from '@mui/material/styles';

export const reviewModeLabels = { confirm: '每次确认', auto: '自动采纳', none: '全部采纳' } as const;

export type ReviewMode = keyof typeof reviewModeLabels;

const reviewModeKeys = ['confirm', 'auto', 'none'] as const;

/**
 * 审核模式选择器（批1 归一）：对话栏与项目信息面板唯一形态。
 * 词汇「每次确认/自动采纳/全部采纳」，值 confirm/auto/none 不动；
 * 激活态 primary 描边+浅底、禁实心——它不是状态章，不进 StatusChip tone 表。
 */
export default function ReviewModePicker({ value, onChange, disabled = false, hint = false }: {
  value: ReviewMode;
  onChange: (mode: ReviewMode) => void;
  disabled?: boolean;
  /** 显示一句说明（全角标点）。 */
  hint?: boolean;
}) {
  return <Box>
    {hint && <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>审核模式：AI 稿件候选的采纳方式，按本书持久保存。</Typography>}
    <ToggleButtonGroup
      exclusive
      size="small"
      value={value}
      disabled={disabled}
      onChange={(_event, next) => { if (next) onChange(next as ReviewMode); }}
      aria-label="审核模式"
      sx={{ '& .MuiToggleButton-root.Mui-selected': (theme) => ({ borderColor: theme.palette.primary.main, bgcolor: alpha(theme.palette.primary.main, 0.08) }) }}
    >
      {reviewModeKeys.map((mode) => <ToggleButton key={mode} value={mode} disabled={disabled}>{reviewModeLabels[mode]}</ToggleButton>)}
    </ToggleButtonGroup>
  </Box>;
}
