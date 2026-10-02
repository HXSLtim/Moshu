'use client';

import { Box, Stack, Typography } from '@mui/material';
import { StatusChip } from '@/components/common/primitives';
import type { CharacterAppearanceResponse } from '@/lib/api/generated/model';

/** 出场类型作者词汇（中性阶）。分类属性走 StatusChip neutral，不占状态色。 */
export const appearanceTypeLabels: Record<string, string> = { main: '主场', supporting: '出场', mentioned: '提及' };

interface CharacterAppearanceListProps {
  appearances: CharacterAppearanceResponse[];
}

/**
 * 出场条目列表：按章节号升序排成一条线（服务端不保证顺序，客户端排一次）。
 * status_changes 是松散 dict（MCP 追踪的形态未定），一期不假渲染。
 */
export default function CharacterAppearanceList({ appearances }: CharacterAppearanceListProps) {
  const sorted = [...appearances].sort((a, b) => a.chapter_number - b.chapter_number);
  return <Stack sx={{ mt: 2 }}>
    {sorted.map((appearance, index) => {
      const last = index === sorted.length - 1;
      return <Box
        key={appearance.id}
        sx={{
          position: 'relative',
          pl: 3.5,
          pb: last ? 0 : 2,
          // 排线：节点圆点 + 段间竖线，全部中性色。
          '&::after': {
            content: '""',
            position: 'absolute',
            left: 0,
            top: '8px',
            width: '7px',
            height: '7px',
            borderRadius: '50%',
            border: '1.5px solid',
            borderColor: 'text.secondary',
            bgcolor: 'background.paper',
          },
          ...(!last && {
            '&::before': {
              content: '""',
              position: 'absolute',
              left: '3px',
              top: '20px',
              bottom: '-2px',
              width: '1px',
              bgcolor: 'divider',
            },
          }),
        }}
      >
        <Stack direction="row" alignItems="center" gap={1} useFlexGap sx={{ flexWrap: 'wrap' }}>
          <Typography variant="subtitle2">第 {appearance.chapter_number} 章</Typography>
          {appearance.appearance_type && (
            <StatusChip
              tone="neutral"
              size="small"
              label={appearanceTypeLabels[appearance.appearance_type] ?? appearance.appearance_type}
            />
          )}
        </Stack>
        {appearance.description && <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>{appearance.description}</Typography>}
      </Box>;
    })}
  </Stack>;
}
