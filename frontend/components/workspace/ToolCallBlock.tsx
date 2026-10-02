'use client';

import React, { useState } from 'react';
import { Box, Chip, Collapse, IconButton, Typography } from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import SearchIcon from '@mui/icons-material/Search';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import EditNoteIcon from '@mui/icons-material/EditNote';
import AltRouteIcon from '@mui/icons-material/AltRoute';
import TravelExploreIcon from '@mui/icons-material/TravelExplore';
import VerifiedIcon from '@mui/icons-material/Verified';

export interface ToolCallEvent {
  name: string;
  status: 'running' | 'read' | 'checked' | 'completed' | 'proposed' | 'drafted';
  data?: { summary?: string } | Record<string, unknown> | null;
}

const TOOL_META: Record<string, { label: string; icon: React.ReactNode; verb: string }> = {
  search_story_bible: { label: '设定账本', icon: <SearchIcon fontSize="inherit" />, verb: '检索' },
  lookup_character: { label: '角色卡', icon: <SearchIcon fontSize="inherit" />, verb: '查阅' },
  read_chapter_digest: { label: '前章简介', icon: <SearchIcon fontSize="inherit" />, verb: '阅读' },
  read_chapter: { label: '正文', icon: <SearchIcon fontSize="inherit" />, verb: '阅读' },
  get_outline: { label: '全书大纲', icon: <SearchIcon fontSize="inherit" />, verb: '查看' },
  search_manuscript: { label: '旧正文', icon: <SearchIcon fontSize="inherit" />, verb: '检索' },
  check_manuscript: { label: '稿件一致性', icon: <VerifiedIcon fontSize="inherit" />, verb: '自查' },
  workflow_continue: { label: '高级续写', icon: <AutoAwesomeIcon fontSize="inherit" />, verb: '执行' },
  write_manuscript: { label: '正文', icon: <AutoAwesomeIcon fontSize="inherit" />, verb: '起草' },
  orchestrate: { label: '任务编排', icon: <AccountTreeIcon fontSize="inherit" />, verb: '编排' },
  rewrite_selection: { label: '选区改写', icon: <EditNoteIcon fontSize="inherit" />, verb: '改写' },
  plot_options: { label: '剧情走向', icon: <AltRouteIcon fontSize="inherit" />, verb: '生成' },
  research_web: { label: '资料检索', icon: <TravelExploreIcon fontSize="inherit" />, verb: '检索' },
};

/** Claude Code 风格的内联工具调用块:一行动词+对象+状态,可展开摘要。 */
export default function ToolCallBlock({ event }: { event: ToolCallEvent }) {
  const [open, setOpen] = useState(false);
  const meta = TOOL_META[event.name] ?? { label: event.name, icon: <SearchIcon fontSize="inherit" />, verb: '调用' };
  const running = event.status === 'running';
  const summary = (event.data as { summary?: string } | null | undefined)?.summary ?? '';
  return (
    <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 0.5, my: 0.25 }}>
      <Chip
        size="small"
        variant="outlined"
        color={running ? 'primary' : 'default'}
        icon={<Box sx={{ fontSize: 13, display: 'flex', alignItems: 'center' }}>{meta.icon}</Box>}
        label={running ? `正在${meta.verb}${meta.label}…` : `已${meta.verb}${meta.label}`}
        onClick={() => setOpen((value) => !value)}
        sx={{ height: 22, '& .MuiChip-label': { fontSize: 12 } }}
      />
      {summary && (
        <>
          <IconButton size="small" sx={{ p: 0.25 }} aria-label={open ? '收起工具详情' : '展开工具详情'} onClick={() => setOpen((value) => !value)}>
            <ExpandMoreIcon sx={{ fontSize: 14, transform: open ? 'rotate(180deg)' : 'none', transition: 'transform .2s' }} />
          </IconButton>
          <Collapse in={open} unmountOnExit sx={{ flex: 1, minWidth: 0 }}>
            <Typography variant="caption" color="text.secondary" sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', display: 'block', py: 0.5 }}>
              {summary}
            </Typography>
          </Collapse>
        </>
      )}
    </Box>
  );
}
