'use client';

import React, { useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Collapse,
  Divider,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import StopIcon from '@mui/icons-material/Stop';
import SendIcon from '@mui/icons-material/Send';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import type { OrchestrateResponse } from '@/lib/api/generated/model/orchestrateResponse';
import { useGenerationTask } from '@/hooks/useGenerationTask';
import { isGenerationPending } from '@/lib/generationJobs';
import WritingProposalActions from '@/components/workspace/WritingProposalActions';
import type { Chapter } from '@/types';

interface OrchestrationPanelProps {
  novelId: number;
  novelLifecycleId?: string;
  chapterId: number | null;
  chapterLifecycleId?: string;
  chapterVersion?: number | null;
  currentContent: string;
  canApply?: boolean;
  onProposalAccepted?: (chapter: Chapter) => void;
}

const KIND_LABEL: Record<string, string> = {
  retrieve: '检索',
  generate: '生成',
  consistency: '一致性',
};

/** 编排任务面板:复合指令 → 持久任务(提交/恢复/停止) → 计划、不确定点与候选提案。 */
export default function OrchestrationPanel(props: OrchestrationPanelProps) {
  const { novelId, novelLifecycleId, chapterId, chapterLifecycleId } = props;
  const [instruction, setInstruction] = useState('');
  const { job, submitting, stopping, error, run, stop } = useGenerationTask<OrchestrateResponse>({
    novelId, novelLifecycleId, chapterId, chapterLifecycleId, kind: 'orchestrate',
  });
  const result = job?.result ?? null;
  const pending = Boolean(job && isGenerationPending(job));
  const canSubmit = Boolean(novelLifecycleId && chapterId && !submitting && !pending && instruction.trim());

  const submit = () => {
    if (!canSubmit) return;
    const payload: Record<string, unknown> = {
      novel_id: novelId,
      chapter_id: chapterId ?? 0,
      current_content: props.currentContent,
      instruction: instruction.trim(),
    };
    if (novelLifecycleId) payload.expected_novel_lifecycle_id = novelLifecycleId;
    if (chapterLifecycleId) payload.expected_chapter_lifecycle_id = chapterLifecycleId;
    void run(payload);
  };

  const plan = Array.isArray(result?.plan?.steps) ? result.plan.steps : [];
  const uncertainties = result?.uncertainties ?? [];
  const consistency = result?.consistency ?? null;

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack spacing={1.5}>
          <TextField
            fullWidth
            multiline
            minRows={2}
            maxRows={5}
            label="复合创作指令"
            value={instruction}
            placeholder="例如:先查林夏和反派的旧怨,据此写一场夜战,写完自查时间线"
            onChange={(event) => setInstruction(event.target.value)}
            disabled={pending || submitting}
          />
          <Stack direction="row" spacing={1}>
            <Button
              size="small"
              variant="contained"
              startIcon={submitting ? <CircularProgress size={14} color="inherit" /> : <SendIcon />}
              disabled={!canSubmit}
              onClick={submit}
            >
              提交编排
            </Button>
            {pending && (
              <Button size="small" color="error" startIcon={<StopIcon />} disabled={stopping} onClick={() => void stop()}>
                停止
              </Button>
            )}
          </Stack>

          {pending && (
            <Alert severity="info">
              编排任务{job?.status === 'running' ? '执行中' : '排队中'},可关闭页面,任务保存在服务器。
            </Alert>
          )}
          {error && <Alert severity="error">{error}</Alert>}
          {job?.status === 'failed' && job.error && <Alert severity="warning">{job.error}</Alert>}
          {job?.status === 'cancelled' && <Alert severity="info">编排已停止。</Alert>}

          <Collapse in={Boolean(result)}>
            <Stack spacing={1.5} divider={<Divider flexItem />}>
              {plan.length > 0 && (
                <Box>
                  <Typography variant="caption" color="text.secondary">执行计划</Typography>
                  <Stack spacing={0.5} sx={{ mt: 0.5 }}>
                    {plan.map((step) => (
                      <Stack key={String(step.id)} direction="row" spacing={1} alignItems="center">
                        <Chip size="small" label={`${KIND_LABEL[String(step.kind)] ?? String(step.kind)} ${step.id}`} />
                        <Typography variant="body2" sx={{ overflowWrap: 'anywhere' }}>
                          {String(step.instruction ?? '')}
                        </Typography>
                      </Stack>
                    ))}
                  </Stack>
                </Box>
              )}

              {uncertainties.length > 0 && (
                <Box>
                  <Stack direction="row" spacing={0.5} alignItems="center">
                    <WarningAmberIcon fontSize="small" color="warning" />
                    <Typography variant="caption" color="text.secondary">模型上报的不确定点</Typography>
                  </Stack>
                  {uncertainties.map((item) => (
                    <Typography key={item} variant="body2" color="warning.dark" sx={{ overflowWrap: 'anywhere' }}>
                      · {item}
                    </Typography>
                  ))}
                </Box>
              )}

              {consistency && (
                <Box>
                  <Typography variant="caption" color="text.secondary">一致性检查</Typography>
                  <Typography variant="body2" color={consistency.has_conflict ? 'error.main' : 'text.primary'}>
                    {consistency.has_conflict
                      ? `发现 ${Array.isArray(consistency.violations) ? consistency.violations.length : 0} 处冲突,采纳前请核对`
                      : '未发现与既有设定的冲突'}
                  </Typography>
                </Box>
              )}

              {result?.content && (
                <Box>
                  <Typography variant="caption" color="text.secondary">候选正文({result.length} 字)</Typography>
                  <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', mt: 0.5 }}>
                    {result.content}
                  </Typography>
                  {result.proposal_id && (
                    <WritingProposalActions
                      novelId={novelId}
                      proposalId={result.proposal_id}
                      chapterId={chapterId}
                      chapterLifecycleId={chapterLifecycleId}
                      chapterVersion={props.chapterVersion ?? undefined}
                      currentContent={props.currentContent}
                      canApply={props.canApply}
                      onProposalAccepted={props.onProposalAccepted}
                    />
                  )}
                </Box>
              )}
            </Stack>
          </Collapse>
        </Stack>
      </CardContent>
    </Card>
  );
}
