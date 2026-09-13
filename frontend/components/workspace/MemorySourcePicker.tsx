'use client';

import { useEffect, useState } from 'react';
import { Alert, MenuItem, Stack, TextField, Typography } from '@mui/material';
import { chapterMemoryApi } from '@/lib/chapterMemory';
import type { ChapterRevision, ChapterRevisionSummary } from '@/types/chapterMemory';
import type { MemorySource } from '@/types/storyMemory';

interface Props { novelId: number; chapterId: number | null; onChange: (source: MemorySource | null, revisionId: string | null) => void; disabled?: boolean; quoteRequired?: boolean }
export default function MemorySourcePicker({ novelId, chapterId, onChange, disabled, quoteRequired = true }: Props) {
  const [revisions, setRevisions] = useState<ChapterRevisionSummary[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [revision, setRevision] = useState<ChapterRevision | null>(null);
  const [quote, setQuote] = useState('');
  const [occurrence, setOccurrence] = useState(0);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    setRevisions([]); setSelectedId(''); setRevision(null); setQuote(''); setError('');
    if (chapterId !== null) void chapterMemoryApi.listRevisions(novelId, chapterId, undefined, controller.signal).then((items) => {
      if (!controller.signal.aborted) { setRevisions(items); setSelectedId(items[0]?.id ?? ''); }
    }).catch(() => { if (!controller.signal.aborted) setError('读取原文版本失败，请关闭后重试。'); });
    return () => controller.abort();
  }, [novelId, chapterId]);
  useEffect(() => {
    const controller = new AbortController();
    setRevision(null); setQuote(''); setOccurrence(0);
    if (selectedId) void chapterMemoryApi.getRevision(novelId, selectedId, controller.signal).then((item) => {
      if (!controller.signal.aborted) setRevision(item);
    }).catch(() => { if (!controller.signal.aborted) setError('来源原文不可用，请选择其他版本。'); });
    return () => controller.abort();
  }, [novelId, selectedId]);
  const starts: number[] = [];
  // 字符位置遵循后端 Unicode 码点，不能使用 JavaScript UTF-16 下标冒充。
  const sourceChars = Array.from(revision?.content ?? '');
  const quoteChars = Array.from(quote);
  if (quoteChars.length) for (let i = 0; i <= sourceChars.length - quoteChars.length; i += 1) {
    if (sourceChars.slice(i, i + quoteChars.length).join('') === quote) starts.push(i);
  }
  const start = starts[occurrence];
  useEffect(() => {
    onChange(revision && quote && start !== undefined ? { revision_id: revision.id, quote, start } : null, revision?.id ?? null);
  }, [revision, quote, start, onChange]);
  return <Stack spacing={1}>
    <Typography variant="caption">从当前编辑章节的已保存原文选择出处。要引用其他章节，请先在编辑器中打开该章。</Typography>
    {chapterId === null && <Alert severity="info">请先选择来源章节。</Alert>}
    {error && <Alert severity="warning">{error}</Alert>}
    {chapterId !== null && !selectedId && !error && <Typography>当前章节还没有可读取的原文版本。</Typography>}
    {revisions.length > 0 && <TextField select label="来源原文版本" value={selectedId} disabled={disabled} onChange={(event) => { setSelectedId(event.target.value); setError(''); }}>
      {revisions.map((item) => <MenuItem key={item.id} value={item.id}>v{item.version} · {item.title}</MenuItem>)}
    </TextField>}
    {revision && <>
      <TextField label="来源原文（只读）" value={revision.content} multiline maxRows={6} slotProps={{ input: { readOnly: true } }} />
      {quoteRequired && <>
        <TextField label="引用原句" multiline minRows={2} value={quote} disabled={disabled} slotProps={{ htmlInput: { maxLength: 500 } }} onChange={(event) => { setQuote(event.target.value); setOccurrence(0); }} helperText={quote && starts.length === 0 ? '请复制原文中完全一致的句子，包含空白与标点。' : '引用只作为证据，保存后仍需核对概括是否准确。'} error={Boolean(quote && !starts.length)} />
        {starts.length > 1 && <TextField select label="引用哪一处" value={occurrence} disabled={disabled} onChange={(event) => setOccurrence(Number(event.target.value))}>
          {starts.map((_value, index) => <MenuItem key={index} value={index}>第 {index + 1} 处</MenuItem>)}
        </TextField>}
      </>}
    </>}
  </Stack>;
}
