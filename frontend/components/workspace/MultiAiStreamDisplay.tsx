'use client';

import { useState, useEffect } from 'react';
import {
  Box,
  Typography,
  Chip,
  Card,
  CardContent,
  Collapse,
  IconButton,
  LinearProgress,
  Fade,
  Grid,
  Avatar,
  Paper,
  useTheme,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import PersonIcon from '@mui/icons-material/Person';
import CreateIcon from '@mui/icons-material/Create';
import RateReviewIcon from '@mui/icons-material/RateReview';
import PublicIcon from '@mui/icons-material/Public';
import PsychologyIcon from '@mui/icons-material/Psychology';
import ArchitectureIcon from '@mui/icons-material/Architecture';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import TypewriterDisplay from './TypewriterDisplay';

interface AgentStreamData {
  agentId: string;
  agentName: string;
  status: 'waiting' | 'thinking' | 'generating' | 'done' | 'error';
  generatedText: string;
  startTime?: Date;
  error?: string;
}

interface MultiAiStreamDisplayProps {
  /** SSE事件流 */
  sseEvents: Array<{
    id: number;
    type: string;
    label: string;
    timestamp: Date;
    agent?: string;
    status?: string;
    data?: any;
  }>;
  /** 当前生成中的文本（来自onChunk） */
  currentGeneration: string;
  /** 是否正在生成 */
  isGenerating: boolean;
  /** 扩展视图的头信息（可折叠）*/
  headerInfo?: string;
}

// Agent 配置映射
const getAgentConfig = (agentName: string) => {
  const lowerName = agentName.toLowerCase();
  if (lowerName.includes('architect') || lowerName.includes('plot')) {
    return { icon: <ArchitectureIcon />, color: '#9c27b0', label: '剧情架构师' }; // Purple
  }
  if (lowerName.includes('character')) {
    return { icon: <PersonIcon />, color: '#ff9800', label: '角色设计师' }; // Orange
  }
  if (lowerName.includes('world') || lowerName.includes('setting')) {
    return { icon: <PublicIcon />, color: '#009688', label: '世界观构建师' }; // Teal
  }
  if (lowerName.includes('writer') || lowerName.includes('author')) {
    return { icon: <CreateIcon />, color: '#2196f3', label: '核心作家' }; // Blue
  }
  if (lowerName.includes('review') || lowerName.includes('critic')) {
    return { icon: <RateReviewIcon />, color: '#4caf50', label: '内容审核员' }; // Green
  }
  return { icon: <PsychologyIcon />, color: '#607d8b', label: 'AI 助手' }; // Grey
};

/**
 * 多AI流式内容显示组件
 * 实时展示多个AI Agent的生成过程和结果
 */
export default function MultiAiStreamDisplay({
  sseEvents,
  currentGeneration,
  isGenerating,
  headerInfo = 'Agent 协同工作台',
}: MultiAiStreamDisplayProps) {
  const theme = useTheme();
  const [agents, setAgents] = useState<Map<string, AgentStreamData>>(new Map());
  const [expanded, setExpanded] = useState(true);

  useEffect(() => {
    if (!isGenerating && agents.size > 0) {
      // 生成结束，5秒后清除所有agent状态 (给用户多一点时间看结果)
      const timer = setTimeout(() => {
        setAgents(new Map());
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [isGenerating, agents.size]);

  useEffect(() => {
    if (sseEvents.length === 0) return;

    setAgents(prev => {
      const newAgents = new Map(prev);
      // 只处理最近的事件，避免处理过旧的数据
      const latestEvents = [...sseEvents]
        .filter(e => e.timestamp >= new Date(Date.now() - 60000))
        .slice(0, 20);

      latestEvents.forEach(event => {
        if (event.type === 'agent' && event.agent && event.status) {
          // 使用 agentName 作为 ID 的一部分，确保同一类型的 agent 状态连续
          const agentId = event.agent;

          if (!newAgents.has(agentId)) {
            // 新的Agent开始工作
            newAgents.set(agentId, {
              agentId,
              agentName: event.agent,
              status: event.status === 'start' ? 'thinking' : 'waiting',
              generatedText: '',
              startTime: new Date(),
            });
          } else {
            // 更新Agent状态
            const agent = newAgents.get(agentId)!;

            if (event.status === 'start') {
              agent.status = 'thinking';
            } else if (event.status === 'generating') {
              agent.status = 'generating';
            } else if (event.status === 'completed') {
              agent.status = 'done';
            } else if (event.status === 'failed') {
              agent.status = 'error';
              agent.error = '执行出错';
            }
          }
        }
      });

      return newAgents;
    });
  }, [sseEvents]);

  useEffect(() => {
    if (!isGenerating || !currentGeneration) return;

    // 将当前生成的文本分配给活跃的agent
    setAgents(prev => {
      const newAgents = new Map(prev);
      let assigned = false;

      // 优先分配给状态为 generating 的 agent
      for (const agent of newAgents.values()) {
        if (agent.status === 'generating') {
          agent.generatedText = currentGeneration;
          assigned = true;
          break;
        }
      }

      // 如果没有 generating 的 agent，尝试分配给 thinking 的 agent (可能状态转换有延迟)
      if (!assigned) {
        for (const agent of newAgents.values()) {
          if (agent.status === 'thinking') {
            agent.status = 'generating'; // 强制更新状态
            agent.generatedText = currentGeneration;
            assigned = true;
            break;
          }
        }
      }

      // 如果还是没有，创建一个默认的 Writer Agent
      if (!assigned && currentGeneration.length > 0) {
        const defaultAgentId = 'Writer Agent';
        if (!newAgents.has(defaultAgentId)) {
          newAgents.set(defaultAgentId, {
            agentId: defaultAgentId,
            agentName: 'Writer Agent',
            status: 'generating',
            generatedText: currentGeneration,
            startTime: new Date(),
          });
        } else {
          const agent = newAgents.get(defaultAgentId)!;
          agent.generatedText = currentGeneration;
          agent.status = 'generating';
        }
      }

      return newAgents;
    });
  }, [currentGeneration, isGenerating]);

  const orderedAgents = Array.from(agents.values()).sort((a, b) => {
    // 排序逻辑：正在生成的优先，其次是思考中，最后是完成/等待
    const statusOrder = { generating: 0, thinking: 1, error: 2, done: 3, waiting: 4 };
    return statusOrder[a.status] - statusOrder[b.status];
  });

  const activeAgentsCount = orderedAgents.filter(a => a.status === 'generating' || a.status === 'thinking').length;
  const completedAgentsCount = orderedAgents.filter(a => a.status === 'done').length;

  if (orderedAgents.length === 0 && !isGenerating) {
    return null;
  }

  return (
    <Card
      elevation={3}
      sx={{
        mb: 3,
        overflow: 'visible',
        border: '1px solid',
        borderColor: isGenerating ? 'primary.main' : 'divider',
        transition: 'border-color 0.3s ease',
        boxShadow: isGenerating ? '0 0 20px rgba(25, 118, 210, 0.15)' : undefined
      }}
    >
      <CardContent sx={{ p: 0 }}>
        {/* 头部信息 */}
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            p: 2,
            background: isGenerating
              ? `linear-gradient(45deg, ${theme.palette.primary.main}15, ${theme.palette.background.paper})`
              : theme.palette.background.paper,
            cursor: 'pointer',
            borderBottom: '1px solid',
            borderColor: 'divider',
          }}
          onClick={() => setExpanded(!expanded)}
        >
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <Box sx={{ position: 'relative' }}>
              <SmartToyIcon
                color={isGenerating ? "primary" : "action"}
                sx={{
                  fontSize: 28,
                  animation: isGenerating ? 'pulse 2s infinite' : 'none',
                  '@keyframes pulse': {
                    '0%': { opacity: 1, transform: 'scale(1)' },
                    '50%': { opacity: 0.7, transform: 'scale(1.1)' },
                    '100%': { opacity: 1, transform: 'scale(1)' },
                  },
                }}
              />
              {isGenerating && (
                <Box
                  sx={{
                    position: 'absolute',
                    top: -2,
                    right: -2,
                    width: 10,
                    height: 10,
                    bgcolor: 'success.main',
                    borderRadius: '50%',
                    border: '2px solid white',
                  }}
                />
              )}
            </Box>

            <Box>
              <Typography variant="subtitle1" fontWeight={700} sx={{ lineHeight: 1.2 }}>
                {headerInfo}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {isGenerating
                  ? `${activeAgentsCount} 个 Agent 正在协作中...`
                  : '等待任务指令'}
              </Typography>
            </Box>
          </Box>

          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            {completedAgentsCount > 0 && (
              <Chip
                icon={<CheckCircleIcon fontSize="small" />}
                label={`${completedAgentsCount} 完成`}
                size="small"
                color="success"
                variant="outlined"
              />
            )}
            <IconButton size="small">
              {expanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
            </IconButton>
          </Box>
        </Box>

        <Collapse in={expanded}>
          <Box sx={{ p: 2, bgcolor: 'grey.50' }}>
            {isGenerating && orderedAgents.length === 0 && (
              <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', py: 4, gap: 2 }}>
                <LinearProgress sx={{ width: '60%', borderRadius: 2 }} />
                <Typography variant="body2" color="text.secondary">
                  正在初始化 Agent 团队...
                </Typography>
              </Box>
            )}

            <Grid container spacing={2}>
              {orderedAgents.map((agent) => {
                const config = getAgentConfig(agent.agentName);
                const isThinking = agent.status === 'thinking';
                const isGenerating = agent.status === 'generating';
                const isDone = agent.status === 'done';
                const isError = agent.status === 'error';

                return (
                  <Grid item xs={12} key={agent.agentId}>
                    <Fade in={true} timeout={500}>
                      <Paper
                        elevation={isGenerating ? 4 : 1}
                        sx={{
                          p: 2,
                          borderLeft: '4px solid',
                          borderLeftColor: isError ? 'error.main' : (isDone ? 'success.main' : config.color),
                          bgcolor: 'background.paper',
                          transition: 'all 0.3s ease',
                          transform: isGenerating ? 'scale(1.01)' : 'scale(1)',
                        }}
                      >
                        <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 2, mb: 1 }}>
                          <Avatar
                            sx={{
                              bgcolor: config.color,
                              width: 40,
                              height: 40,
                              boxShadow: isGenerating ? `0 0 10px ${config.color}` : 'none',
                            }}
                          >
                            {config.icon}
                          </Avatar>

                          <Box sx={{ flex: 1 }}>
                            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 0.5 }}>
                              <Typography variant="subtitle2" fontWeight={700}>
                                {agent.agentName}
                                <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                                  {config.label}
                                </Typography>
                              </Typography>

                              <Chip
                                label={
                                  isThinking ? '思考中...' :
                                    isGenerating ? '正在撰写' :
                                      isDone ? '已完成' :
                                        isError ? '错误' : '等待中'
                                }
                                size="small"
                                color={
                                  isThinking ? 'warning' :
                                    isGenerating ? 'primary' :
                                      isDone ? 'success' :
                                        isError ? 'error' : 'default'
                                }
                                variant={isGenerating ? 'filled' : 'outlined'}
                                sx={{
                                  height: 24,
                                  animation: isThinking ? 'pulse 1.5s infinite' : 'none'
                                }}
                              />
                            </Box>

                            {/* 思考状态的进度条 */}
                            {isThinking && (
                              <Box sx={{ width: '100%', mt: 1, mb: 1 }}>
                                <LinearProgress color="warning" sx={{ height: 4, borderRadius: 2 }} />
                              </Box>
                            )}

                            {/* 生成的内容 */}
                            {(isGenerating || agent.generatedText) && (
                              <Box sx={{ mt: 1 }}>
                                <TypewriterDisplay
                                  currentText={agent.generatedText}
                                  currentAgent={agent.agentName}
                                  status={agent.status === 'generating' ? 'generating' : 'done'}
                                  label="输出内容"
                                  maxHeight={200}
                                  simpleMode={true} // 新增属性，简化 TypewriterDisplay 的外框
                                />
                              </Box>
                            )}

                            {/* 错误信息 */}
                            {isError && agent.error && (
                              <Typography variant="body2" color="error" sx={{ mt: 1 }}>
                                {agent.error}
                              </Typography>
                            )}
                          </Box>
                        </Box>
                      </Paper>
                    </Fade>
                  </Grid>
                );
              })}
            </Grid>
          </Box>
        </Collapse>
      </CardContent>
    </Card>
  );
}

