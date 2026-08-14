'use client';

import { useState, useCallback, useEffect } from 'react';
import {
  Card,
  CardContent,
  Typography,
  Button,
  Box,
  Divider,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Chip,
  Alert,
  CircularProgress,
} from '@mui/material';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import LightbulbIcon from '@mui/icons-material/Lightbulb';
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh';
import WarningIcon from '@mui/icons-material/Warning';
import { api } from '@/lib/api';

export interface PlotOption {
  id: number;
  title: string;
  summary: string;
  impact?: string | null;
  risk?: string | null;
}

interface PlotOptionsGeneratorProps {
  novelId: number;
  chapterId: number | null;
  currentContent: string;
  onPlotSelected: (option: PlotOption) => void;
  onError: (error: string) => void;
  /** 选择剧情后是否自动触发续写 */
  onPlotSelectedAndContinue?: (option: PlotOption) => void;
  /** 外部传入的初始选项 */
  initialOptions?: Omit<PlotOption, 'id'>[] | PlotOption[];
}

export default function PlotOptionsGenerator({
  novelId,
  chapterId,
  currentContent,
  onPlotSelected,
  onError,
  onPlotSelectedAndContinue,
  initialOptions,
}: PlotOptionsGeneratorProps) {
  const [plotOptions, setPlotOptions] = useState<PlotOption[]>(() => {
    if (initialOptions && initialOptions.length > 0) {
      return initialOptions.map((opt, index) => ({
        ...opt,
        id: (opt as any).id || Date.now() + index,
      }));
    }
    return [];
  });
  const [plotOptionsLoading, setPlotOptionsLoading] = useState(false);
  const [selectedPlotOptionId, setSelectedPlotOptionId] = useState<number | null>(null);

  useEffect(() => {
    if (initialOptions && initialOptions.length > 0) {
      setPlotOptions(initialOptions.map((opt, index) => ({
        ...opt,
        id: (opt as any).id || Date.now() + index,
      })));
    }
  }, [initialOptions]);

  const handleGeneratePlotOptions = useCallback(async () => {
    if (!chapterId) {
      onError('未找到当前章节');
      return;
    }

    if (!currentContent.trim()) {
      onError('章节内容为空，无法生成剧情选项');
      return;
    }

    setPlotOptionsLoading(true);
    setPlotOptions([]);
    setSelectedPlotOptionId(null);

    try {
      const result = await api.getPlotOptions({
        novel_id: novelId,
        chapter_id: chapterId,
        current_content: currentContent,
        num_options: 4,
      });

      setPlotOptions(result.options);
    } catch (err) {
      onError(err instanceof Error ? err.message : '生成剧情选项失败');
    } finally {
      setPlotOptionsLoading(false);
    }
  }, [novelId, chapterId, currentContent, onError]);

  const handleSelectPlotOption = useCallback((option: PlotOption) => {
    setSelectedPlotOptionId(option.id);
    onPlotSelected(option);
  }, [onPlotSelected]);

  const handleSelectAndContinue = useCallback((option: PlotOption) => {
    setSelectedPlotOptionId(option.id);
    if (onPlotSelectedAndContinue) {
      onPlotSelectedAndContinue(option);
    } else {
      onPlotSelected(option);
    }
  }, [onPlotSelected, onPlotSelectedAndContinue]);

  const getRiskColor = (risk: string | null | undefined) => {
    if (!risk) return 'default';
    const lowerRisk = risk.toLowerCase();
    if (lowerRisk.includes('高') || lowerRisk.includes('high')) return 'error';
    if (lowerRisk.includes('中') || lowerRisk.includes('medium')) return 'warning';
    return 'success';
  };

  const getImpactColor = (impact: string | null | undefined) => {
    if (!impact) return 'default';
    const lowerImpact = impact.toLowerCase();
    if (lowerImpact.includes('重大') || lowerImpact.includes('major')) return 'error';
    if (lowerImpact.includes('中等') || lowerImpact.includes('moderate')) return 'warning';
    return 'info';
  };

  return (
    <Card sx={{ mb: 2 }}>
      <CardContent>
        <Box
          sx={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            mb: 1,
          }}
        >
          <Typography variant="subtitle2">剧情走向</Typography>
          <Button
            size="small"
            variant="outlined"
            startIcon={<TrendingUpIcon />}
            onClick={handleGeneratePlotOptions}
            disabled={plotOptionsLoading || !chapterId}
          >
            {plotOptionsLoading ? '生成中...' : '生成选项'}
          </Button>
        </Box>
        <Divider sx={{ my: 1 }} />

        {plotOptionsLoading && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
            <CircularProgress size={24} />
            <Typography variant="body2" color="text.secondary" sx={{ ml: 2 }}>
              AI正在分析当前剧情，生成可能的发展方向...
            </Typography>
          </Box>
        )}

        {plotOptions.length > 0 ? (
          <Box>
            <Alert severity="info" sx={{ mb: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
              <LightbulbIcon fontSize="small" />
              <Box>
                <Typography variant="body2" fontWeight="medium">
                  AI 已为您生成 {plotOptions.length} 个剧情方向
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  点击选项查看详情，或直接点击「选择并续写」快速开始
                </Typography>
              </Box>
            </Alert>

            <List>
              {plotOptions.map((option) => (
                <ListItem key={option.id} disablePadding sx={{ mb: 1 }}>
                  <Box
                    sx={{
                      border: '1px solid',
                      borderColor: selectedPlotOptionId === option.id ? 'primary.main' : 'divider',
                      borderRadius: 1,
                      overflow: 'hidden',
                      transition: 'all 0.2s',
                      '&:hover': {
                        borderColor: 'primary.main',
                        boxShadow: 1,
                      },
                    }}
                  >
                    <ListItemButton
                      selected={selectedPlotOptionId === option.id}
                      onClick={() => handleSelectPlotOption(option)}
                      sx={{ pb: 1 }}
                    >
                      <ListItemText
                        disableTypography
                        primary={
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                            <LightbulbIcon color="primary" fontSize="small" />
                            <Typography variant="subtitle2" fontWeight="medium">
                              {option.title}
                            </Typography>
                          </Box>
                        }
                        secondary={
                          <Box>
                            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                              {option.summary}
                            </Typography>

                            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                              {option.impact && (
                                <Chip
                                  label={`影响: ${option.impact}`}
                                  size="small"
                                  color={getImpactColor(option.impact) as any}
                                  variant="outlined"
                                />
                              )}
                              {option.risk && (
                                <Chip
                                  label={`风险: ${option.risk}`}
                                  size="small"
                                  color={getRiskColor(option.risk) as any}
                                  variant="outlined"
                                  icon={<WarningIcon fontSize="small" />}
                                />
                              )}
                            </Box>
                          </Box>
                        }
                      />
                    </ListItemButton>
                    {onPlotSelectedAndContinue && (
                      <Box sx={{ px: 2, pb: 1.5, pt: 0, bgcolor: 'action.hover' }}>
                        <Button
                          fullWidth
                          size="small"
                          variant="contained"
                          color="primary"
                          startIcon={<AutoFixHighIcon />}
                          onClick={() => handleSelectAndContinue(option)}
                        >
                          选择并续写
                        </Button>
                      </Box>
                    )}
                  </Box>
                </ListItem>
              ))}
            </List>

            {selectedPlotOptionId && !onPlotSelectedAndContinue && (
              <Alert severity="success" sx={{ mt: 2 }}>
                <Typography variant="body2" fontWeight="medium">
                  ✓ 已选择剧情方向
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  现在可以在下方「AI续写助手」中点击「AI续写」按钮，AI 将参考此方向发展故事
                </Typography>
              </Alert>
            )}
          </Box>
        ) : !plotOptionsLoading ? (
          <Box sx={{ textAlign: 'center', py: 3 }}>
            <TrendingUpIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 1 }} />
            <Typography variant="body2" color="text.secondary" gutterBottom>
              基于当前章节内容，AI 将为您生成多个可能的剧情发展方向
            </Typography>
            <Typography variant="caption" color="text.secondary">
              点击上方「生成选项」按钮开始
            </Typography>
          </Box>
        ) : null}
      </CardContent>
    </Card>
  );
}
