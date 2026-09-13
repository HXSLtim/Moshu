'use client';

import { useState } from 'react';
import { Alert, Button, Card, CardContent, MenuItem, Stack, TextField, Typography } from '@mui/material';
import { useGenerationTask } from '@/hooks/useGenerationTask';
import type { WritingScope } from '@/hooks/useWritingProposal';
import WritingProposalActions from './WritingProposalActions';

interface Props extends WritingScope { selectedText: string; selectionStart: number | null; selectionEnd: number | null; onError: (error: string) => void }
interface Result { rewritten_text: string; proposal_id?: string }
const typeLabels = { polish: '润色优化', rewrite: '重新改写', shorten: '精简缩短', extend: '扩展延伸' };
export default function TextRewriter(props: Props) {
  const task = useGenerationTask<Result>({ ...props, kind: 'rewrite' });
  const [rewriteType, setRewriteType] = useState<keyof typeof typeLabels>('polish');
  const [styleHint, setStyleHint] = useState('');
  const [targetLength, setTargetLength] = useState('');
  const [error, setError] = useState('');
  const [edited, setEdited] = useState<{ jobId: string; text: string } | null>(null);
  const [source, setSource] = useState<{ requestId: string; text: string; content: string } | null>(null);
  const result = task.job?.status === 'completed' ? task.job.result : null;
  const candidate = edited?.jobId === task.job?.id ? edited?.text ?? '' : result?.rewritten_text ?? '';
  const currentSource = source?.requestId === task.job?.request_id ? source : null;
  const stale = Boolean(currentSource && currentSource.content !== props.currentContent);
  const run = () => {
    try {
      if (!props.canApply || !props.chapterId) throw new Error('请先保存正文并完成身份核验，再生成可采纳候选');
      if (props.selectionStart === null || props.selectionEnd === null || !props.selectedText) throw new Error('请先选择要改写的文本');
      if (Array.from(props.selectedText).length > 20000) throw new Error('每次最多改写 20000 字符，请缩小选区');
      if (props.currentContent.slice(props.selectionStart, props.selectionEnd) !== props.selectedText) throw new Error('选区已发生变化，请重新选择文本');
      const length = (rewriteType === 'extend' || rewriteType === 'shorten') && targetLength ? Number(targetLength) : undefined;
      if (length !== undefined && (!Number.isInteger(length) || length < 10 || length > 5000)) throw new Error('目标字数需要是 10 到 5000 的整数');
      const requestId = crypto.randomUUID();
      setSource({ requestId, text: props.selectedText, content: props.currentContent }); setEdited(null); setError('');
      void task.run({ novel_id: props.novelId, chapter_id: props.chapterId, original_text: props.selectedText,
        expected_novel_lifecycle_id: props.novelLifecycleId, expected_chapter_lifecycle_id: props.chapterLifecycleId,
        selection_start: Array.from(props.currentContent.slice(0, props.selectionStart)).length,
        selection_end: Array.from(props.currentContent.slice(0, props.selectionEnd)).length,
        rewrite_type: rewriteType, style_hint: styleHint || undefined, target_length: length }, requestId);
    } catch (failure) { const message = failure instanceof Error ? failure.message : '无法开始改写'; setError(message); props.onError(message); }
  };
  return <Card sx={{ mb: 2 }}><CardContent><Stack spacing={2}>
    <Typography variant="subtitle2">局部改写</Typography>
    {task.jobs.length > 1 && <TextField select label="本章改写任务记录" value={task.job?.id ?? ''} disabled={task.loading || task.pending || task.stopping} onChange={(event) => task.select(event.target.value)}>{task.jobs.map((job) => <MenuItem key={job.id} value={job.id}>{new Date(job.created_at).toLocaleString()} · {{ queued: '排队中', running: '改写中', completed: '已完成', failed: '失败', cancelled: '已取消' }[job.status]}</MenuItem>)}</TextField>}
    {(error || task.error) && <Alert severity="warning" action={task.error ? <Button onClick={task.refresh}>刷新任务</Button> : undefined}>{error || task.error}</Alert>}
    {task.job?.status === 'failed' && <Alert severity="warning">{task.job.error || '改写失败，请核对选区后重试。'}</Alert>}
    {task.job?.status === 'cancelled' && <Alert severity="info">改写任务已取消。</Alert>}
    {!props.canApply && <Typography variant="caption">请先保存正文，再生成或采纳改写。</Typography>}
    {!props.selectedText && !result && <Typography color="text.secondary">请在编辑器中选择要改写的文本。</Typography>}
    {props.selectedText && <>
      <Typography sx={{ whiteSpace: 'pre-wrap', maxHeight: 120, overflow: 'auto' }}>{props.selectedText}</Typography>
      <TextField select label="改写类型" value={rewriteType} disabled={task.pending} onChange={(event) => setRewriteType(event.target.value as keyof typeof typeLabels)}>{Object.entries(typeLabels).map(([value, label]) => <MenuItem key={value} value={value}>{label}</MenuItem>)}</TextField>
      <TextField label="风格提示（可选）" value={styleHint} disabled={task.pending} slotProps={{ htmlInput: { maxLength: 1000 } }} onChange={(event) => setStyleHint(event.target.value)} />
      {(rewriteType === 'extend' || rewriteType === 'shorten') && <TextField label="目标字数（可选）" type="number" value={targetLength} disabled={task.pending} onChange={(event) => setTargetLength(event.target.value)} />}
      <Button variant="contained" disabled={task.loading || task.pending || !props.canApply || !props.chapterId} onClick={run}>开始{typeLabels[rewriteType]}</Button>
    </>}
    {task.pending && <><Typography role="status">{task.job?.status === 'queued' ? '改写任务已排队' : '正在改写…'}</Typography><Button disabled={task.submitting || task.stopping} onClick={() => void task.stop()}>停止改写</Button></>}
    {result && <>
      <Typography variant="subtitle2">原文与候选对照</Typography>
      {currentSource && <TextField label="生成时的原文" multiline minRows={3} maxRows={10} value={currentSource.text} slotProps={{ input: { readOnly: true } }} />}
      <TextField label="改写候选稿" multiline minRows={3} maxRows={14} value={candidate} slotProps={{ htmlInput: { maxLength: 500000 } }} onChange={(event) => setEdited({ jobId: task.job!.id, text: event.target.value })} />
      {stale && <Alert severity="warning">正文已发生变化，不能直接替换。请重新选择文本并生成改写，候选稿仍可复制。</Alert>}
      <Typography variant="caption">候选保存在服务器。采纳前会核对来源版本和原选区，再将你确认的改写保存为新版本。</Typography>
      {result.proposal_id ? <WritingProposalActions key={result.proposal_id} {...props} canApply={props.canApply && !stale} proposalId={result.proposal_id} candidateContent={candidate} acceptLabel="采纳并替换原选区" /> : <Alert severity="warning">此结果缺少服务端候选记录，可复制参考，请重新生成后采纳。</Alert>}
    </>}
  </Stack></CardContent></Card>;
}
