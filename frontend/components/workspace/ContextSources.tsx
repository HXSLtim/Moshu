'use client';

import { useEffect, useRef, useState } from 'react';
import { Accordion, AccordionDetails, AccordionSummary, Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, Typography } from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { chapterMemoryApi } from '@/lib/chapterMemory';
import type { ChapterRevision } from '@/types/chapterMemory';
import type { ChapterDigestSource, ContextManifest } from '@/types/context';

interface Props {
  novelId: number;
  manifest?: ContextManifest | null;
}

function SourceDetails({ novelId, manifest }: Props & { manifest: ContextManifest }) {
  const [selected, setSelected] = useState<Omit<ChapterDigestSource, "kind"> | null>(null);
  const [revision, setRevision] = useState<ChapterRevision | null>(null);
  const [error, setError] = useState('');
  const request = useRef<AbortController | null>(null);
  const validScope = manifest.scope.novel_id === novelId;

  useEffect(() => () => request.current?.abort(), []);

  const close = () => {
    request.current?.abort();
    request.current = null;
    setSelected(null);
    setRevision(null);
    setError('');
  };

  const open = async (source: Omit<ChapterDigestSource, "kind">) => {
    if (!validScope) return;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setSelected(source);
    setRevision(null);
    setError('');
    try {
      const result = await chapterMemoryApi.getRevision(novelId, source.source_revision_id, controller.signal);
      if (controller.signal.aborted || request.current !== controller) return;
      if (result.id !== source.source_revision_id || result.chapter_id !== source.chapter_id || result.version !== source.source_version || result.content_hash !== source.content_hash) {
        setError('来源版本与本次参考记录不一致，暂时无法展示。');
        return;
      }
      setRevision(result);
    } catch {
      if (!controller.signal.aborted && request.current === controller) setError('无法读取这份来源原文，可能已删除或暂时无法访问。对话回复仍然保留。');
    }
  };

  return <Stack spacing={1}>
    <Typography variant="caption" color="text.secondary">这是生成时实际参考的记忆记录，不代表读过全书。后续改稿不会改写此记录；链接打开当时简介依据的原文版本。</Typography>
    {!validScope ? <Alert severity="warning">来源记录与当前作品不一致，无法查看。</Alert> : <>
      {manifest.sources.length === 0 && <Typography variant="body2">暂无可用前文简介。</Typography>}
      {manifest.sources.map((source) => <Button key={source.id} size="small" sx={{ justifyContent: 'flex-start', textAlign: 'left' }} onClick={() => void open(source)}>
        第 {source.chapter_number} 章 · {source.title} · 原文 v{source.source_version}
      </Button>)}
      {(manifest.structured_sources ?? []).map((source) => <Stack key={`${source.kind}-${source.id}`} spacing={0.5}>
        <Typography variant="caption" color="text.secondary">{source.kind === 'source_excerpt' ? '原文摘录' : source.kind === 'core_state' ? '核心状态' : '大纲参考'}</Typography>
        <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>{source.text}</Typography>
        {source.source_refs.length === 0 && <Typography variant="caption" color="text.secondary">作者直接设定</Typography>}
        {source.source_refs.map((reference) => <Button key={`${reference.revision_id}-${reference.start}`} size="small" onClick={() => void open({ id: source.id, title: source.title, chapter_id: reference.chapter_id, chapter_number: reference.chapter_number, source_revision_id: reference.revision_id, source_version: reference.source_version, content_hash: reference.content_hash })}>核对第 {reference.chapter_number} 章原文 v{reference.source_version}</Button>)}
      </Stack>)}
      {manifest.warnings.length > 0 && <Stack spacing={0.5}>
        {manifest.warnings.map((warning, index) => <Typography key={index} variant="caption" color="text.secondary">{warning}</Typography>)}
      </Stack>}
    </>}
    <Dialog open={Boolean(selected)} fullWidth maxWidth="md" onClose={close}>
      <DialogTitle>{selected ? `参考来源 · ${selected.title} · 原文 v${selected.source_version}` : '参考来源'}</DialogTitle>
      <DialogContent dividers>
        {error ? <Alert severity="warning">{error}</Alert> : revision ? <>
          <Typography variant="caption" color="text.secondary">只读历史原文，不会替换当前正文；此处不是 AI 提取的简介文本。</Typography>
          <Typography component="pre" sx={{ fontFamily: 'inherit', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{revision.content || '（空正文）'}</Typography>
        </> : <Typography role="status">正在读取来源原文…</Typography>}
      </DialogContent>
      <DialogActions><Button onClick={close}>关闭原文</Button></DialogActions>
    </Dialog>
  </Stack>;
}

export default function ContextSources({ novelId, manifest }: Props) {
  const [expanded, setExpanded] = useState(false);
  if (!manifest) return null;
  return <Accordion disableGutters expanded={expanded} onChange={(_event, value) => setExpanded(value)} sx={{ mt: 1, boxShadow: 'none' }}>
    <AccordionSummary expandIcon={<ExpandMoreIcon />}><Typography variant="caption">{manifest.structured_sources?.length ? "本次参考记忆" : "本次参考简介"}</Typography></AccordionSummary>
    <AccordionDetails>
      {expanded && <SourceDetails key={`${novelId}-${manifest.fingerprint}`} novelId={novelId} manifest={manifest} />}
    </AccordionDetails>
  </Accordion>;
}
