'use client';

import React, { useState } from 'react';
import { Box, Card, CardContent, Chip, Collapse, IconButton, Typography } from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import CloseIcon from '@mui/icons-material/Close';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import EditNoteIcon from '@mui/icons-material/EditNote';
import VerifiedIcon from '@mui/icons-material/Verified';
import AltRouteIcon from '@mui/icons-material/AltRoute';
import TravelExploreIcon from '@mui/icons-material/TravelExplore';

export type ActionKind = 'orchestrate' | 'continue' | 'rewrite' | 'consistency' | 'plot' | 'research';

export const ACTION_KINDS: Array<{ kind: ActionKind; label: string; hint: string; icon: React.ReactNode }> = [
  { kind: 'orchestrate', label: '编排任务', hint: '复合指令分解为检索、生成与检查', icon: <AccountTreeIcon fontSize="small" /> },
  { kind: 'continue', label: '高级续写', hint: '三角色工作流续写本章', icon: <AutoAwesomeIcon fontSize="small" /> },
  { kind: 'rewrite', label: '选区改写', hint: '改写编辑器中选中的文字', icon: <EditNoteIcon fontSize="small" /> },
  { kind: 'consistency', label: '一致性自查', hint: '核对正文与已确认设定', icon: <VerifiedIcon fontSize="small" /> },
  { kind: 'plot', label: '剧情走向', hint: '生成多个可选发展方向', icon: <AltRouteIcon fontSize="small" /> },
  { kind: 'research', label: '资料检索', hint: '搜索背景与专业知识', icon: <TravelExploreIcon fontSize="small" /> },
];

export interface ActionCardState {
  id: string;
  kind: ActionKind;
  created_at: string;
}

interface ActionCardProps {
  state: ActionCardState;
  onClose: (id: string) => void;
  children: React.ReactNode;
}

/** 对话流里的动作卡片容器:能力面板内嵌于卡片,作者手动从「+」菜单创建。 */
export default function ActionCard({ state, onClose, children }: ActionCardProps) {
  const [collapsed, setCollapsed] = useState(false);
  const meta = ACTION_KINDS.find((item) => item.kind === state.kind);
  return (
    <Card variant="outlined" sx={{ mb: 3, mt: 3 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 1.5, py: 1 }}>
        {meta?.icon}
        <Typography variant="subtitle2">{meta?.label ?? state.kind}</Typography>
        <Chip size="small" label="创作工具" variant="outlined" sx={{ height: 20 }} />
        <Box sx={{ flex: 1 }} />
        <IconButton size="small" aria-label={collapsed ? '展开卡片' : '折叠卡片'} onClick={() => setCollapsed((value) => !value)}>
          {collapsed ? <ExpandMoreIcon fontSize="small" /> : <ExpandLessIcon fontSize="small" />}
        </IconButton>
        <IconButton size="small" aria-label="关闭卡片" onClick={() => onClose(state.id)}>
          <CloseIcon fontSize="small" />
        </IconButton>
      </Box>
      <Collapse in={!collapsed}>
        <CardContent sx={{ pt: 0 }}>{children}</CardContent>
      </Collapse>
    </Card>
  );
}
