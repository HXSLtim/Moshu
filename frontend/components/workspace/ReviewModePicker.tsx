'use client';

import { Box, ToggleButton, ToggleButtonGroup, Tooltip, Typography } from '@mui/material';
import { alpha } from '@mui/material/styles';

export const reviewModeLabels = { confirm: '每次确认', auto: '自动采纳', none: '全部采纳' } as const;

export type ReviewMode = keyof typeof reviewModeLabels;

const reviewModeKeys = ['confirm', 'auto', 'none'] as const;

/** 快裁统一副文本：悬停档位即得该档解释，两处调用点同句同形。 */
const reviewModeHints: Record<ReviewMode, string> = {
  confirm: 'AI 的每次改稿都先给你过目，你确认才写入正文。',
  auto: '通过一致性检查的直接写入，有疑问的留给你决定。',
  none: 'AI 的改稿全部直接写入，不再一一过目。',
};

/**
 * 审核模式选择器（批1 归一）：对话栏与项目信息面板唯一形态。
 * 说明句与三档副文本都收在组件内部（刻度只写一处），值 confirm/auto/none 不动；
 * 激活态 primary 描边+浅底、禁实心——它不是状态章，不进 StatusChip tone 表。
 */
export default function ReviewModePicker({ value, onChange, disabled = false }: {
  value: ReviewMode;
  onChange: (mode: ReviewMode) => void;
  disabled?: boolean;
}) {
  return <Box>
    <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>审核模式：AI 的改稿怎么入库，按本书保存。</Typography>
    <ToggleButtonGroup
      exclusive
      size="small"
      value={value}
      disabled={disabled}
      onChange={(_event, next) => { if (next) onChange(next as ReviewMode); }}
      aria-label="审核模式"
      sx={{ '& .MuiToggleButton-root.Mui-selected': (theme) => ({ borderColor: theme.palette.primary.main, bgcolor: alpha(theme.palette.primary.main, 0.08) }) }}
    >
      {reviewModeKeys.map((mode) => <Tooltip key={mode} title={reviewModeHints[mode]}><ToggleButton value={mode} aria-label={reviewModeLabels[mode]} disabled={disabled}>{reviewModeLabels[mode]}</ToggleButton></Tooltip>)}
    </ToggleButtonGroup>
  </Box>;
}
