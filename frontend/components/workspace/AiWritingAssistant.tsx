'use client';

import {
  useState,
  useCallback,
  forwardRef,
  useImperativeHandle,
  useRef,
  useEffect,
} from 'react';
import {
  Card,
  CardContent,
  Typography,
  TextField,
  Button,
  Box,
  LinearProgress,
  FormControlLabel,
  Switch,
  Collapse,
  Slider,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Alert,
  Chip,
  CircularProgress,
  Tooltip,
  IconButton,
  Paper,
  Fade,
} from '@mui/material';
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh';
import StopIcon from '@mui/icons-material/Stop';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import TuneIcon from '@mui/icons-material/Tune';
import { api } from '@/lib/api';
import type { SSEEvent } from '@/lib/sse';
import type {
  AgentWorkflowTrace,
  GenerationFinalConsistency,
  GenerationMetadata,
} from '@/types';
import AgentWorkflowVisualization from './AgentWorkflowVisualization';
import MultiAiStreamDisplay from './MultiAiStreamDisplay';
import PlotOptionsGenerator, { PlotOption } from './PlotOptionsGenerator';

const CONSISTENCY_CHECK_LABELS: Record<string, string> = {
  rule_engine: '规则引擎',
  knowledge_graph: '知识图谱',
  timeline: '时间线',
  emotion_state: '情绪状态',
};

interface AiWritingAssistantProps {
  novelId: number;
  chapterId: number | null;
  currentContent: string;
  onContentGenerated: (newContent: string) => void;
  onError: (error: string) => void;
  /** 工作流追踪变更回调，用于外部工作流可视化侧栏 */
  onWorkflowTraceChange?: (trace: AgentWorkflowTrace | null) => void;
  /** 用户选择的剧情走向提示，用于影响续写方向 */
  plotDirectionHint?: string | null;
  /** 将生成内容应用到下一章节的回调（可选） */
  onApplyToNextChapter?: (generatedText: string) => Promise<void>;
}

export interface AiWritingAssistantRef {
  triggerContinue: (overrideInstruction?: string) => void;
}

const AiWritingAssistant = forwardRef<AiWritingAssistantRef, AiWritingAssistantProps>(function AiWritingAssistant({
  novelId,
  chapterId,
  currentContent,
  onContentGenerated,
  onError,
  onWorkflowTraceChange,
  plotDirectionHint,
  onApplyToNextChapter,
}, ref) {
  // AI生成状态
  const [aiGenerating, setAiGenerating] = useState(false);
  const [generationStep, setGenerationStep] = useState('');
  const [generatedText, setGeneratedText] = useState('');
  const [finalConsistency, setFinalConsistency] = useState<GenerationFinalConsistency | null>(null);
  const [applyingToNextChapter, setApplyingToNextChapter] = useState(false);
  const generatedTextRef = useRef('');
  const abortControllerRef = useRef<AbortController | null>(null);
  const generationIdRef = useRef(0);
  const renderFrameRef = useRef<number | null>(null);
  const generationBaseContentRef = useRef('');

  // 剧情选项
  const [detectedPlotOptions, setDetectedPlotOptions] = useState<PlotOption[]>([]);

  // 流式显示增强
  const [streamHeaderInfo, setStreamHeaderInfo] = useState('Agent实时生成状态');

  // 用户设置
  const [aiInstruction, setAiInstruction] = useState('');
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [targetLength, setTargetLength] = useState(500);
  const [styleStrength, setStyleStrength] = useState(0.7);
  const [pace, setPace] = useState<'slow' | 'medium' | 'fast'>('medium');
  const [tone, setTone] = useState<'neutral' | 'tense' | 'relaxed' | 'sad' | 'joyful'>('neutral');
  const [useRagStyle, setUseRagStyle] = useState(true);

  // SSE事件日志（增强版，包含时间戳和元数据）
  const [sseEvents, setSseEvents] = useState<
    {
      id: number;
      type: string;
      label: string;
      timestamp: Date;
      agent?: string;
      status?: string;
      data?: any;
    }[]
  >([]);
  const sseEventIdRef = useRef(0);

  // Agent 工作流追踪
  const [workflowTrace, setWorkflowTrace] = useState<AgentWorkflowTrace | null>(null);

  const flushGeneratedText = useCallback(() => {
    if (renderFrameRef.current !== null) {
      cancelAnimationFrame(renderFrameRef.current);
      renderFrameRef.current = null;
    }
    setGeneratedText(generatedTextRef.current);
  }, []);

  const scheduleGeneratedTextRender = useCallback(() => {
    if (renderFrameRef.current !== null) return;
    renderFrameRef.current = requestAnimationFrame(() => {
      renderFrameRef.current = null;
      setGeneratedText(generatedTextRef.current);
    });
  }, []);

  useEffect(() => {
    generationIdRef.current += 1;
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    if (renderFrameRef.current !== null) {
      cancelAnimationFrame(renderFrameRef.current);
      renderFrameRef.current = null;
    }
    generatedTextRef.current = '';
    setGeneratedText('');
    setAiGenerating(false);
    setGenerationStep('');
    setFinalConsistency(null);
    setSseEvents([]);
    setWorkflowTrace(null);
    onWorkflowTraceChange?.(null);

    return () => {
      generationIdRef.current += 1;
      abortControllerRef.current?.abort();
      abortControllerRef.current = null;
      if (renderFrameRef.current !== null) {
        cancelAnimationFrame(renderFrameRef.current);
        renderFrameRef.current = null;
      }
    };
  }, [chapterId, onWorkflowTraceChange]);

  const handleAiContinue = useCallback(async (overrideInstruction?: string) => {
    if (!chapterId) {
      onError('未找到当前章节');
      return;
    }

    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;
    const generationId = generationIdRef.current + 1;
    generationIdRef.current = generationId;
    generationBaseContentRef.current = currentContent;
    setAiGenerating(true);
    setGenerationStep('正在连接AI...');
    setGeneratedText('');
    generatedTextRef.current = '';
    setFinalConsistency(null);
    setSseEvents([]);
    setDetectedPlotOptions([]);
    setStreamHeaderInfo('Agent实时生成状态');
    // 每次新一轮生成前重置工作流追踪
    onWorkflowTraceChange?.(null);

    try {
      await api.continueChapterStream(
        {
          novel_id: novelId,
          chapter_id: chapterId,
          current_content: currentContent,
          target_length: targetLength,
          style_strength: styleStrength,
          pace,
          tone,
          use_rag_style: useRagStyle,
          plot_direction_hint: [plotDirectionHint, overrideInstruction ?? aiInstruction].filter(Boolean).join('\n') || undefined,
        },
        {
          onChunk: (chunk: string) => {
            if (generationIdRef.current !== generationId) return;
            generatedTextRef.current += chunk;
            scheduleGeneratedTextRender();
            setGenerationStep('AI正在创作...');
          },
          onEvent: (event: SSEEvent) => {
            if (generationIdRef.current !== generationId || event.type === 'chunk') return;
            const timestamp = new Date();
            setSseEvents(prev => {
              const id = sseEventIdRef.current++;
              let label = '';
              let agent = undefined;
              let status = undefined;

              if (event.type === 'agent') {
                const eventAgent = (event as any).agent ?? '';
                const eventStatus = (event as any).status ?? '';
                label = `${eventAgent}:${eventStatus}`;
                agent = eventAgent;
                status = eventStatus;
                // Update the progress text
                setGenerationStep(`${eventAgent} ${eventStatus}...`);
              } else if (event.type === 'generation') {
                label = '生成阶段';
              } else if (event.type === 'chunk') {
                label = '输出正文片段';
              } else if (event.type === 'metadata') {
                label = '同步元数据（文风与工作流）';
              } else if (event.type === 'done') {
                label = '生成流程完成';
              } else {
                label = event.type || 'unknown';
              }

              const next = [
                { id, type: event.type ?? 'unknown', label, timestamp, agent, status, data: (event as any).data },
                ...prev,
              ];
              return next.slice(0, 20);
            });
          },
          onMetadata: (metadata: GenerationMetadata) => {
            if (generationIdRef.current !== generationId) return;
            if (metadata.final_consistency) {
              setFinalConsistency(metadata.final_consistency);
            }
            // 更新文风提示
            if (metadata.style_features) {
              setGenerationStep(`应用文风特征: ${metadata.style_features.slice(0, 2).join(', ')}`);
            }

            // 更新工作流追踪数据
            if (metadata.workflow_trace) {
              const trace = metadata.workflow_trace as AgentWorkflowTrace;
              setWorkflowTrace(trace);
              // 透出工作流追踪数据，供外部使用
              onWorkflowTraceChange?.(trace);
            }

            // 更新Agent数量显示
            if (metadata.agents || metadata.agent_names) {
              const agents = metadata.agents || metadata.agent_names || [];
              if (agents.length > 0) {
                setStreamHeaderInfo(`Agent实时生成状态 (${agents.length}个Agent)`);
              }
            }
          },
          onDone: () => {
            if (generationIdRef.current !== generationId) return;
            flushGeneratedText();
            setGenerationStep('生成完成');
            setAiGenerating(false);
            abortControllerRef.current = null;

            // 尝试解析剧情选项 JSON
            try {
              let text = generatedTextRef.current.trim();
              // 移除可能存在的 markdown 代码块标记
              if (text.startsWith('```')) {
                text = text.replace(/^```(json)?/, '').replace(/```$/, '');
              }
              text = text.trim();

              if (text.startsWith('{') && text.includes('"options"')) {
                const data = JSON.parse(text);
                if (data.options && Array.isArray(data.options)) {
                  console.log('[AiWritingAssistant] Detected plot options:', data.options);
                  setDetectedPlotOptions(data.options);
                  // 如果是纯选项输出，则清空生成的文本显示，避免重复
                  setGeneratedText('');
                  generatedTextRef.current = '';
                }
              }
            } catch {
              // 解析失败则忽略，视为普通文本
              console.log('[AiWritingAssistant] JSON parse failed, treating as text');
            }
          },
        },
        { signal: controller.signal },
      );
    } catch (err) {
      if (generationIdRef.current !== generationId) return;
      if (err instanceof Error && err.name === 'AbortError') {
        setGenerationStep('已停止生成');
      } else if (err instanceof Error) {
        onError(err.message);
        setGenerationStep('生成失败');
      } else {
        onError('AI生成失败');
        setGenerationStep('生成失败');
      }
      setAiGenerating(false);
      abortControllerRef.current = null;
    }
  }, [novelId, chapterId, currentContent, targetLength, styleStrength, pace, tone, useRagStyle, plotDirectionHint, aiInstruction, onError, onWorkflowTraceChange, flushGeneratedText, scheduleGeneratedTextRender]);

  const handlePlotOptionSelected = useCallback((option: PlotOption) => {
    setAiInstruction(`剧情走向：${option.title}\n${option.summary}`);
    setDetectedPlotOptions([]);
  }, []);

  const handlePlotOptionSelectedAndContinue = useCallback((option: PlotOption) => {
    const instruction = `剧情走向：${option.title}\n${option.summary}`;
    setAiInstruction(instruction);
    setDetectedPlotOptions([]);
    // 立即触发续写
    handleAiContinue(instruction);
  }, [handleAiContinue]);

  const handleStopGeneration = useCallback(() => {
    if (abortControllerRef.current) {
      generationIdRef.current += 1;
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
      flushGeneratedText();
      setAiGenerating(false);
      setGenerationStep('已停止生成');
    }
  }, [flushGeneratedText]);

  const handleApplyGenerated = useCallback(() => {
    if (generatedText) {
      console.log('[DEBUG] handleApplyGenerated 被调用');
      console.log('[DEBUG] currentContent 长度:', currentContent.length);
      console.log('[DEBUG] generatedText 长度:', generatedText.length);
      const newContent = currentContent + generatedText;
      console.log('[DEBUG] 合并后内容长度:', newContent.length);
      // 使用最新的 currentContent，避免闭包问题
      onContentGenerated(newContent);
      setGeneratedText('');
      setGenerationStep('');
      setFinalConsistency(null);
      setWorkflowTrace(null); // 清空工作流追踪
    }
  }, [generatedText, currentContent, onContentGenerated]);

  const handleApplyToNextChapter = useCallback(async () => {
    if (!generatedText) {
      return;
    }

    if (!onApplyToNextChapter) {
      onError('当前不支持将内容应用到下一章节');
      return;
    }

    setApplyingToNextChapter(true);
    try {
      await onApplyToNextChapter(generatedText);
      setGeneratedText('');
      generatedTextRef.current = '';
      setGenerationStep('');
      setFinalConsistency(null);
      setWorkflowTrace(null);
      onWorkflowTraceChange?.(null);
    } catch (error) {
      const message = error instanceof Error ? error.message : '创建下一章节失败';
      onError(message);
      setGenerationStep('应用失败，生成内容已保留，可重试');
    } finally {
      setApplyingToNextChapter(false);
    }
  }, [generatedText, onApplyToNextChapter, onError, onWorkflowTraceChange]);

  const handleDiscardGenerated = useCallback(() => {
    setGeneratedText('');
    setGenerationStep('');
    setFinalConsistency(null);
  }, []);

  // 暴露给父组件的方法
  useImperativeHandle(ref, () => ({
    triggerContinue: handleAiContinue,
  }), [handleAiContinue]);

  const generatedFromStaleContent =
    Boolean(generatedText) && generationBaseContentRef.current !== currentContent;

  return (
    <Card sx={{ mb: 2, overflow: 'visible' }}>
      <CardContent>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <SmartToyIcon color="primary" />
            <Typography variant="subtitle2" fontWeight="600">
              AI续写助手
            </Typography>
            {aiGenerating && (
              <Chip
                label="生成中"
                size="small"
                color="primary"
                sx={{
                  animation: 'pulse 1.5s infinite',
                  '@keyframes pulse': {
                    '0%': { opacity: 1 },
                    '50%': { opacity: 0.7 },
                    '100%': { opacity: 1 },
                  }
                }}
              />
            )}
          </Box>
          <Tooltip title="AI参数设置">
            <IconButton
              size="small"
              aria-label="切换 AI 参数设置"
              onClick={() => setAdvancedOpen((open) => !open)}
            >
              <TuneIcon />
            </IconButton>
          </Tooltip>
        </Box>

        {/* AI指令输入（可留空，仅用于精细控制） */}
        <TextField
          fullWidth
          multiline
          rows={3}
          label="补充写作指令（可留空）"
          value={aiInstruction}
          onChange={(e) => setAiInstruction(e.target.value)}
          placeholder="可选：补充你对语气、细节或额外事件的要求。不填时仅按当前内容和剧情走向续写。"
          helperText="如果已经在上方选择了剧情走向，这里可以留空。只有在你想进一步精细指定写法时再填写。"
          sx={{ mb: 2 }}
          disabled={aiGenerating}
        />

        {/* 生成/停止按钮：遵循全局按钮设计规范 */}
        <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
          {!aiGenerating ? (
            <Button
              fullWidth
              variant="contained"
              color="primary"
              startIcon={<AutoFixHighIcon />}
              onClick={() => handleAiContinue()}
              disabled={!chapterId}
            >
              AI续写
            </Button>
          ) : (
            <Button
              fullWidth
              variant="outlined"
              color="error"
              startIcon={<StopIcon />}
              onClick={handleStopGeneration}
            >
              停止生成
            </Button>
          )}
        </Box>

        {/* 生成进度 */}
        {aiGenerating && (
          <Fade in={aiGenerating}>
            <Paper
              elevation={0}
              sx={{
                p: 2,
                mb: 2,
                bgcolor: 'primary.50',
                border: '1px solid',
                borderColor: 'primary.200',
                borderRadius: 2
              }}
            >
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                <CircularProgress size={16} />
                <Typography variant="body2" fontWeight="500" color="primary.main">
                  AI正在思考中...
                </Typography>
              </Box>
              <LinearProgress
                sx={{
                  mb: 1,
                  height: 6,
                  borderRadius: 3,
                  backgroundColor: 'primary.100',
                  '& .MuiLinearProgress-bar': {
                    borderRadius: 3,
                  }
                }}
              />
              <Typography variant="caption" color="primary.dark" sx={{ fontWeight: 500 }}>
                {generationStep || '正在分析文本结构...'}
              </Typography>
            </Paper>
          </Fade>
        )}

        {/* Agent 工作流可视化 */}
        <AgentWorkflowVisualization
          workflowTrace={workflowTrace}
          isGenerating={aiGenerating}
        />

        {/* 剧情选项生成器 (当检测到 JSON 输出时显示) */}
        {detectedPlotOptions.length > 0 && (
          <PlotOptionsGenerator
            novelId={novelId}
            chapterId={chapterId}
            currentContent={currentContent}
            onPlotSelected={handlePlotOptionSelected}
            onPlotSelectedAndContinue={handlePlotOptionSelectedAndContinue}
            onError={onError}
            initialOptions={detectedPlotOptions}
          />
        )}

        {/* 生成的文本预览 */}
        {generatedText && (
          <Fade in={Boolean(generatedText)}>
            <Paper
              elevation={2}
              sx={{
                mb: 2,
                overflow: 'hidden',
                border: '1px solid',
                borderColor: 'success.200',
              }}
            >
              <Box sx={{ p: 2, bgcolor: 'success.50', borderBottom: '1px solid', borderColor: 'success.200' }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <AutoFixHighIcon fontSize="small" color="success" />
                  <Typography variant="subtitle2" fontWeight="600" color="success.dark">
                    AI生成内容预览
                  </Typography>
                </Box>
              </Box>
              {generatedFromStaleContent && (
                <Alert severity="warning" sx={{ mx: 2, mt: 2 }}>
                  生成期间正文已发生变化，本次结果基于生成开始时的版本。应用前请确认衔接位置。
                </Alert>
              )}
              {finalConsistency?.is_complete === false && (
                <Alert severity="warning" sx={{ mx: 2, mt: 2 }}>
                  <Typography variant="body2" fontWeight="600">
                    部分一致性检查未执行
                  </Typography>
                  {finalConsistency.checks_skipped.length > 0 && (
                    <Typography variant="caption" display="block">
                      未执行：{finalConsistency.checks_skipped
                        .map((check) => CONSISTENCY_CHECK_LABELS[check] ?? check)
                        .join('、')}
                    </Typography>
                  )}
                </Alert>
              )}
              {finalConsistency?.has_conflict && (
                <Alert
                  severity={finalConsistency.retry_exhausted ? 'error' : 'warning'}
                  sx={{ mx: 2, mt: 2 }}
                >
                  <Typography variant="body2" fontWeight="600">
                    {finalConsistency.retry_exhausted
                      ? '一致性检查重试已耗尽，当前仍是冲突稿'
                      : '当前生成稿存在一致性冲突'}
                  </Typography>
                  {finalConsistency.violations.slice(0, 3).map((violation) => (
                    <Typography key={violation} variant="caption" display="block">
                      · {violation}
                    </Typography>
                  ))}
                </Alert>
              )}
              <Box
                sx={{
                  p: 2,
                  maxHeight: 200,
                  overflow: 'auto',
                  bgcolor: 'background.paper',
                }}
              >
                <Typography
                  variant="body2"
                  sx={{
                    whiteSpace: 'pre-wrap',
                    lineHeight: 1.6,
                    fontFamily: '"Noto Serif SC", serif',
                  }}
                >
                  {generatedText}
                </Typography>
              </Box>
              <Box sx={{ p: 2, bgcolor: 'grey.50', display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
                <Button
                  variant="outlined"
                  size="small"
                  onClick={handleDiscardGenerated}
                  sx={{ minWidth: 80 }}
                >
                  丢弃
                </Button>
                <Button
                  variant="contained"
                  color="primary"
                  size="small"
                  onClick={handleApplyGenerated}
                  sx={{
                    minWidth: 100,
                  }}
                >
                  应用到当前章节
                </Button>
                <Button
                  variant="contained"
                  color="secondary"
                  size="small"
                  onClick={() => void handleApplyToNextChapter()}
                  sx={{
                    minWidth: 120,
                  }}
                  disabled={!onApplyToNextChapter || applyingToNextChapter}
                >
                  {applyingToNextChapter ? '正在创建...' : '应用到下一章节'}
                </Button>
              </Box>
            </Paper>
          </Fade>
        )}

        {/* 高级设置 */}
        <FormControlLabel
          control={
            <Switch
              checked={advancedOpen}
              onChange={(e) => setAdvancedOpen(e.target.checked)}
            />
          }
          label="高级设置"
          sx={{ mb: 1 }}
        />

        <Collapse in={advancedOpen}>
          <Box sx={{ mt: 2 }}>
            {/* 目标长度 */}
            <Typography variant="caption" gutterBottom>
              目标长度: {targetLength} 字
            </Typography>
            <Slider
              value={targetLength}
              onChange={(_, value) => setTargetLength(value as number)}
              min={100}
              max={2000}
              step={50}
              sx={{ mb: 2 }}
              disabled={aiGenerating}
            />

            {/* 文风强度 */}
            <Typography variant="caption" gutterBottom>
              文风强度: {Math.round(styleStrength * 100)}%
            </Typography>
            <Slider
              value={styleStrength}
              onChange={(_, value) => setStyleStrength(value as number)}
              min={0}
              max={1}
              step={0.1}
              sx={{ mb: 2 }}
              disabled={aiGenerating}
            />

            {/* 节奏控制 */}
            <FormControl fullWidth sx={{ mb: 2 }}>
              <InputLabel>节奏</InputLabel>
              <Select
                value={pace}
                onChange={(e) => setPace(e.target.value as typeof pace)}
                disabled={aiGenerating}
              >
                <MenuItem value="slow">缓慢</MenuItem>
                <MenuItem value="medium">适中</MenuItem>
                <MenuItem value="fast">快速</MenuItem>
              </Select>
            </FormControl>

            {/* 情感基调 */}
            <FormControl fullWidth sx={{ mb: 2 }}>
              <InputLabel>情感基调</InputLabel>
              <Select
                value={tone}
                onChange={(e) => setTone(e.target.value as typeof tone)}
                disabled={aiGenerating}
              >
                <MenuItem value="neutral">中性</MenuItem>
                <MenuItem value="tense">紧张</MenuItem>
                <MenuItem value="relaxed">轻松</MenuItem>
                <MenuItem value="sad">悲伤</MenuItem>
                <MenuItem value="joyful">欢快</MenuItem>
              </Select>
            </FormControl>

            {/* RAG文风开关 */}
            <FormControlLabel
              control={
                <Switch
                  checked={useRagStyle}
                  onChange={(e) => setUseRagStyle(e.target.checked)}
                  disabled={aiGenerating}
                />
              }
              label="使用RAG文风分析"
            />
          </Box>
        </Collapse>

        {/* Agent流程显示 */}
        {(aiGenerating || sseEvents.length > 0) && (
          <Box sx={{ mt: 2 }}>
            {/* 多AI流式显示组件（增强版） */}
            <MultiAiStreamDisplay
              sseEvents={sseEvents}
              currentGeneration={generatedText}
              isGenerating={aiGenerating}
              headerInfo={streamHeaderInfo}
            />

            {/* 传统的事件列表（保留作为回退） - 已注释，使用 MultiAiStreamDisplay 替代
            <Box sx={{ mt: 2 }}>
              <Typography variant="subtitle2" gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <SmartToyIcon fontSize="small" color="primary" />
                处理流程日志
                {aiGenerating && (
                  <Chip
                    label="进行中"
                    size="small"
                    color="primary"
                    sx={{
                      animation: 'pulse 1.5s infinite',
                      '@keyframes pulse': {
                        '0%': { opacity: 1 },
                        '50%': { opacity: 0.7 },
                        '100%': { opacity: 1 },
                      }
                    }}
                  />
                )}
              </Typography>
              <Divider sx={{ mb: 1 }} />

              <Box
                sx={{
                  maxHeight: 150,
                  overflow: 'auto',
                  bgcolor: 'grey.50',
                  borderRadius: 1,
                  p: 1.5,
                  border: '1px solid',
                  borderColor: 'grey.200'
                }}
              >
                {sseEvents.length === 0 && aiGenerating && (
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                    <CircularProgress size={12} />
                    <Typography variant="body2" color="text.secondary">
                      正在初始化Agent...
                    </Typography>
                  </Box>
                )}

                {sseEvents.map((event, index) => (
                  <Box
                    key={event.id}
                    sx={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 1,
                      mb: 0.5,
                      opacity: aiGenerating && index === 0 ? 1 : 0.8,
                      transition: 'opacity 0.3s ease'
                    }}
                  >
                    {aiGenerating && index === 0 ? (
                      <CircularProgress size={12} color="primary" />
                    ) : (
                      <Box
                        sx={{
                          width: 12,
                          height: 12,
                          borderRadius: '50%',
                          bgcolor: getEventColor(event.type),
                          flexShrink: 0
                        }}
                      />
                    )}
                    <Typography
                      variant="body2"
                      sx={{
                        fontSize: '0.8rem',
                        fontFamily: 'monospace',
                        color: aiGenerating && index === 0 ? 'primary.main' : 'text.secondary'
                      }}
                    >
                      [{event.timestamp.toLocaleTimeString()}] {event.label}
                    </Typography>
                  </Box>
                ))}

                {aiGenerating && (
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 1, pt: 1, borderTop: '1px dashed', borderColor: 'grey.300' }}>
                    <CircularProgress size={12} />
                    <Typography variant="body2" color="primary.main" sx={{ fontWeight: 500 }}>
                      {generationStep || 'Agent正在处理...'}
                    </Typography>
                  </Box>
                )}
              </Box>
            </Box>
            */}
          </Box>
        )}
      </CardContent>
    </Card>
  );
});

export default AiWritingAssistant;
