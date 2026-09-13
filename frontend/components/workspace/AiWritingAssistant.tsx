'use client';

import { forwardRef, useImperativeHandle, useState } from 'react';
import { Alert, Button, Card, CardContent, Collapse, FormControlLabel, MenuItem, Slider, Stack, Switch, TextField, Typography } from '@mui/material';
import { useGenerationTask } from '@/hooks/useGenerationTask';
import type { WritingScope } from '@/hooks/useWritingProposal';
import type { AgentWorkflowTrace, GenerationFinalConsistency } from '@/types';
import AgentWorkflowVisualization from './AgentWorkflowVisualization';
import WritingProposalActions from './WritingProposalActions';
import ContextSources from './ContextSources';
import type { ContextManifest } from '@/types/context';

interface Props extends WritingScope { onError: (error: string) => void; plotDirectionHint?: string | null }
interface Result { content: string; proposal_id?: string; final_consistency?: GenerationFinalConsistency; workflow_trace?: AgentWorkflowTrace | null; context_manifest?: ContextManifest | null }
export interface AiWritingAssistantRef { triggerContinue: (instruction?: string) => void }
const checkLabels: Record<string, string> = { rule_engine: '规则引擎', knowledge_graph: '知识图谱', timeline: '时间线', emotion_state: '情绪状态' };

const AiWritingAssistant = forwardRef<AiWritingAssistantRef, Props>(function AiWritingAssistant(props, ref) {
  const task = useGenerationTask<Result>({ ...props, kind: 'continue' });
  const [instruction, setInstruction] = useState('');
  const [advanced, setAdvanced] = useState(false);
  const [targetLength, setTargetLength] = useState(500);
  const [styleStrength, setStyleStrength] = useState(0.7);
  const [pace, setPace] = useState('medium');
  const [tone, setTone] = useState('neutral');
  const [useRagStyle, setUseRagStyle] = useState(true);
  const run = (override?: string) => {
    if (!props.canApply || !props.chapterId) { props.onError('请先保存正文并完成身份核验，再生成可采纳候选'); return; }
    void task.run({ novel_id: props.novelId, chapter_id: props.chapterId, current_content: props.currentContent,
      expected_novel_lifecycle_id: props.novelLifecycleId, expected_chapter_lifecycle_id: props.chapterLifecycleId,
      target_length: targetLength, style_strength: styleStrength, pace, tone, use_rag_style: useRagStyle,
      plot_direction_hint: [props.plotDirectionHint, override ?? instruction].filter(Boolean).join('\n') || undefined });
  };
  useImperativeHandle(ref, () => ({ triggerContinue: run }));
  const result = task.job?.status === 'completed' ? task.job.result : null;
  const consistency = result?.final_consistency;
  return <Card sx={{ boxShadow: 'none' }}><CardContent><Stack spacing={2}>
    <Typography variant="subtitle2">高级续写</Typography>
    <Typography variant="caption" color="text.secondary">生成任务会保存在服务器，重新打开本章可恢复进度和最近候选。</Typography>
    {task.jobs.length > 1 && <TextField select label="本章续写任务记录" value={task.job?.id ?? ''} disabled={task.loading || task.pending || task.stopping} onChange={(event) => task.select(event.target.value)}>{task.jobs.map((job) => <MenuItem key={job.id} value={job.id}>{new Date(job.created_at).toLocaleString()} · {{ queued: '排队中', running: '生成中', completed: '已完成', failed: '失败', cancelled: '已取消' }[job.status]}</MenuItem>)}</TextField>}
    {task.error && <Alert severity="warning" action={<Button onClick={task.refresh}>刷新任务</Button>}>{task.error}</Alert>}
    {task.job?.status === 'failed' && <Alert severity="warning">{task.job.error || '本次续写失败，请核对正文后重新生成。'}</Alert>}
    {task.job?.status === 'cancelled' && <Alert severity="info">续写任务已取消。</Alert>}
    {!props.canApply && <Alert severity="info">请先保存正文，再生成或采纳候选。</Alert>}
    <TextField label="续写要求（可选）" multiline minRows={2} value={instruction} disabled={task.pending} slotProps={{ htmlInput: { maxLength: 4000 } }} onChange={(event) => setInstruction(event.target.value)} />
    <Stack direction="row" gap={1}>
      <Button variant="contained" disabled={task.loading || task.pending || !props.canApply || !props.chapterId} onClick={() => run()}>AI续写</Button>
      <Button onClick={() => setAdvanced((value) => !value)}>文风与节奏设置</Button>
      {task.pending && <Button disabled={task.stopping || task.submitting} onClick={() => void task.stop()}>停止续写</Button>}
    </Stack>
    {task.pending && <Typography role="status">{task.submitting ? '正在保存任务…' : task.job?.status === 'queued' ? '续写任务已排队' : '正在生成续写…'}</Typography>}
    <Collapse in={advanced}><Stack spacing={2}>
      <Typography>目标字数：{targetLength}</Typography><Slider aria-label="续写目标字数" value={targetLength} min={100} max={5000} step={100} disabled={task.pending} onChange={(_event, value) => setTargetLength(value as number)} />
      <Typography>文风强度：{styleStrength}</Typography><Slider aria-label="文风强度" value={styleStrength} min={0} max={1} step={0.1} disabled={task.pending} onChange={(_event, value) => setStyleStrength(value as number)} />
      <TextField select label="叙事节奏" value={pace} disabled={task.pending} onChange={(event) => setPace(event.target.value)}>{Object.entries({ slow: '缓慢', medium: '适中', fast: '快速' }).map(([value, label]) => <MenuItem key={value} value={value}>{label}</MenuItem>)}</TextField>
      <TextField select label="情感基调" value={tone} disabled={task.pending} onChange={(event) => setTone(event.target.value)}>{Object.entries({ neutral: '中性', tense: '紧张', relaxed: '轻松', sad: '悲伤', joyful: '欢快' }).map(([value, label]) => <MenuItem key={value} value={value}>{label}</MenuItem>)}</TextField>
      <FormControlLabel control={<Switch checked={useRagStyle} disabled={task.pending} onChange={(_event, value) => setUseRagStyle(value)} />} label="使用 RAG 文风分析" />
    </Stack></Collapse>
    {result && <>
      <Typography variant="subtitle2">续写候选</Typography><Typography sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', lineHeight: 1.9 }}>{result.content}</Typography>
      {consistency?.has_conflict && <Alert severity="warning">{consistency.retry_exhausted ? '一致性检查重试已耗尽，当前仍是冲突稿' : '当前生成稿存在一致性冲突'}{consistency.violations?.map((item, index) => <Typography key={index} variant="body2">· {item}</Typography>)}</Alert>}
      {consistency && !consistency.is_complete && <Alert severity="warning">部分一致性检查未执行<Typography variant="body2">未执行：{consistency.checks_skipped.map((name) => checkLabels[name] ?? name).join('、')}</Typography></Alert>}
      {result.proposal_id ? <WritingProposalActions key={result.proposal_id} {...props} proposalId={result.proposal_id} /> : <Alert severity="warning">此结果缺少服务端候选记录，可复制参考，请重新生成后采纳。</Alert>}
      <ContextSources novelId={props.novelId} manifest={result.context_manifest} />
      {result.workflow_trace && <AgentWorkflowVisualization workflowTrace={result.workflow_trace} />}
    </>}
  </Stack></CardContent></Card>;
});
export default AiWritingAssistant;
