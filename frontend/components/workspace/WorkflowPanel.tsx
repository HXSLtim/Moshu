'use client';

import React from 'react';
import {
  Box,
  Card,
  CardContent,
  Typography,
  Chip,
  Divider,
  List,
  ListItemButton,
  ListItemText,
  ListItemIcon,
  Tooltip,
} from '@mui/material';
import TimelineIcon from '@mui/icons-material/Timeline';
import StorageIcon from '@mui/icons-material/Storage';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import SecurityIcon from '@mui/icons-material/Security';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import type { AgentWorkflowTrace, AgentWorkflowStep } from '@/types';

interface WorkflowPanelProps {
  workflowTrace: AgentWorkflowTrace | null | undefined;
}

/**
 * 多Agent工作流可视化侧栏（简化时间线视图）
 *
 * 说明：
 * - 只依赖后端返回的AgentWorkflowTrace结构
 * - 当前实现为只读视图，不包含交互控制
 */
export default function WorkflowPanel({ workflowTrace }: WorkflowPanelProps) {
  if (!workflowTrace || !workflowTrace.steps || workflowTrace.steps.length === 0) {
    return null;
  }

  const steps = workflowTrace.steps;

  const getStepIcon = (step: AgentWorkflowStep) => {
    switch (step.type) {
      case 'rag':
        return <StorageIcon fontSize="small" />;
      case 'llm':
        return <SmartToyIcon fontSize="small" />;
      case 'consistency':
        return <SecurityIcon fontSize="small" />;
      default:
        return <TimelineIcon fontSize="small" />;
    }
  };

  const formatDuration = (step: AgentWorkflowStep) => {
    if (!step.duration_ms) return '-';
    if (step.duration_ms < 1000) return `${step.duration_ms} ms`;
    return `${(step.duration_ms / 1000).toFixed(1)} s`;
  };

  const totalDuration = (() => {
    const first = steps[0];
    const last = steps[steps.length - 1];
    if (!first.started_at || !last.finished_at) return undefined;
    const start = new Date(first.started_at).getTime();
    const end = new Date(last.finished_at).getTime();
    if (!start || !end || end <= start) return undefined;
    const diff = end - start;
    if (diff < 1000) return `${diff} ms`;
    return `${(diff / 1000).toFixed(1)} s`;
  })();

  return (
    <Card sx={{ mb: 2 }}>
      <CardContent>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <TimelineIcon color="primary" />
            <Typography variant="subtitle2" fontWeight={600}>
              工作流
            </Typography>
          </Box>
          <Chip
            size="small"
            label={workflowTrace.trigger || '多Agent续写'}
            variant="outlined"
          />
        </Box>

        {/* 摘要区 */}
        <Box sx={{ mb: 2 }}>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
            {workflowTrace.summary || '本次AI续写的内部执行步骤'}
          </Typography>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            {typeof totalDuration === 'string' && (
              <Chip size="small" label={`总耗时 ${totalDuration}`} color="default" />
            )}
            <Chip size="small" label={`${steps.length} 个步骤`} variant="outlined" />
          </Box>
        </Box>

        <Divider sx={{ mb: 1 }} />

        {/* 时间线列表 */}
        <List dense sx={{ maxHeight: 260, overflow: 'auto' }}>
          {steps.map((step, index) => (
            <Tooltip
              key={step.id + index}
              title={step.description || step.title}
              placement="left"
              arrow
            >
              <ListItemButton
                sx={{
                  alignItems: 'flex-start',
                  mb: 0.5,
                  borderRadius: 1,
                  '&:hover': {
                    bgcolor: 'action.hover',
                  },
                }}
              >
                <ListItemIcon sx={{ minWidth: 32, mt: 0.5 }}>
                  {getStepIcon(step)}
                </ListItemIcon>
                <ListItemText
                  disableTypography
                  primary={
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                      <Typography variant="body2" fontWeight={500} noWrap>
                        {step.title}
                      </Typography>
                      {step.agent_name && (
                        <Chip
                          size="small"
                          label={step.agent_name}
                          sx={{ maxWidth: 120 }}
                        />
                      )}
                    </Box>
                  }
                  secondary={
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.25 }}>
                      <Typography variant="caption" color="text.secondary">
                        {formatDuration(step)}
                      </Typography>
                      <Typography
                        variant="caption"
                        color="text.secondary"
                        sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}
                      >
                        <InfoOutlinedIcon fontSize="inherit" />
                        {step.type}
                      </Typography>
                    </Box>
                  }
                />
              </ListItemButton>
            </Tooltip>
          ))}
        </List>
      </CardContent>
    </Card>
  );
}
