'use client';

import { useEffect, useRef, useState } from 'react';
import { Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, Typography } from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { chapterMemoryApi } from '@/lib/chapterMemory';
import type { ChapterDigestStatus, ChapterRevision, ChapterRevisionSummary } from '@/types/chapterMemory';
import type { Chapter } from '@/types';

interface Props {
  novelId: number;
  chapterId: number | null;
  currentVersion: number;
  novelLifecycleId?: string;
  chapterLifecycleId?: string;
  currentContent?: string;
  canRestore?: boolean;
  onVersionRestored?: (chapter: Chapter) => void;
}
const POLL_LIMIT = 60;
const isPending = (data: ChapterDigestStatus) => data.job?.state === 'queued' || data.job?.state === 'running';
const errorText = (error: unknown) => error instanceof Error ? error.message : '读取章节记忆失败，请重试';

function MemoryDetails(props: Props & { chapterId: number }) {
  const { novelId, chapterId, currentVersion } = props;
  const latest = useRef(props);
  latest.current = props;
  const [data, setData] = useState<ChapterDigestStatus | null>(null);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [pollStopped, setPollStopped] = useState(false);
  const [rebuilding, setRebuilding] = useState(false);
  const [revisions, setRevisions] = useState<ChapterRevisionSummary[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [revision, setRevision] = useState<ChapterRevision | null>(null);
  const [revisionOpen, setRevisionOpen] = useState(false);
  const [revisionError, setRevisionError] = useState('');
  const [restoreConfirm, setRestoreConfirm] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const mutation = useRef<AbortController | null>(null);
  const operations = useRef(new Set<AbortController>());
  const historyController = useRef<AbortController | null>(null);
  const revisionController = useRef<AbortController | null>(null);
  const rebuildController = useRef<AbortController | null>(null);

  useEffect(() => {
    const active = operations.current;
    return () => { active.forEach((controller) => controller.abort()); active.clear(); };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let polls = 0;
    setPollStopped(false);
    setError('');
    async function load() {
      try {
        const result = await chapterMemoryApi.getDigest(novelId, chapterId, controller.signal);
        if (controller.signal.aborted) return;
        setData(result);
        if (isPending(result) && result.worker_enabled) {
          if (polls < POLL_LIMIT) {
            polls += 1;
            timer = setTimeout(() => { void load(); }, 2000);
          } else setPollStopped(true);
        }
      } catch (failure) {
        if (!controller.signal.aborted) setError(errorText(failure));
      }
    }
    void load();
    return () => { controller.abort(); if (timer) clearTimeout(timer); };
  }, [novelId, chapterId, currentVersion, refresh]);

  const rebuild = async () => {
    if (rebuildController.current) return;
    const controller = new AbortController();
    rebuildController.current = controller;
    operations.current.add(controller);
    setRebuilding(true);
    setError('');
    try {
      const job = await chapterMemoryApi.rebuild(novelId, chapterId, controller.signal);
      if (controller.signal.aborted) return;
      setData((previous) => previous ? { ...previous, job } : previous);
      setRefresh((value) => value + 1);
    } catch (failure) {
      if (!controller.signal.aborted) setError(errorText(failure));
    } finally {
      operations.current.delete(controller);
      rebuildController.current = null;
      if (!controller.signal.aborted) setRebuilding(false);
    }
  };

  const loadHistory = async (before?: number) => {
    historyController.current?.abort();
    const controller = new AbortController();
    historyController.current = controller;
    operations.current.add(controller);
    setHistoryOpen(true);
    setHistoryLoading(true);
    setError('');
    try {
      const items = await chapterMemoryApi.listRevisions(novelId, chapterId, before, controller.signal);
      if (controller.signal.aborted) return;
      setRevisions((previous) => before === undefined ? items : [...previous, ...items]);
      setHasMore(items.length === 20);
    } catch (failure) {
      if (!controller.signal.aborted) setError(errorText(failure));
    } finally {
      operations.current.delete(controller);
      if (!controller.signal.aborted) setHistoryLoading(false);
    }
  };

  const viewRevision = async (id: string) => {
    revisionController.current?.abort();
    const controller = new AbortController();
    revisionController.current = controller;
    operations.current.add(controller);
    setRevisionOpen(true);
    setRevision(null);
    setRevisionError('');
    setRestoreConfirm(false);
    try {
      const result = await chapterMemoryApi.getRevision(novelId, id, controller.signal);
      if (!controller.signal.aborted) setRevision(result);
    } catch (failure) {
      if (!controller.signal.aborted) setRevisionError(errorText(failure));
    } finally { operations.current.delete(controller); }
  };

  const restore = async () => {
    const snapshot = latest.current;
    if (!revision || mutation.current || !snapshot.canRestore || !snapshot.novelLifecycleId || !snapshot.chapterLifecycleId) return;
    const controller = new AbortController();
    mutation.current = controller; operations.current.add(controller);
    setRestoring(true); setRevisionError('');
    try {
      const chapter = await chapterMemoryApi.restoreRevision(novelId, revision.id, {
        expected_version: snapshot.currentVersion,
        expected_novel_lifecycle_id: snapshot.novelLifecycleId,
        expected_chapter_lifecycle_id: snapshot.chapterLifecycleId,
      }, controller.signal);
      if (controller.signal.aborted) return;
      setRestoreConfirm(false);
      const current = latest.current;
      if (!current.canRestore || current.currentVersion !== snapshot.currentVersion || current.currentContent !== snapshot.currentContent) {
        setRevisionError('历史版本已恢复到服务器；你在恢复期间又编辑了正文，本机新稿已保留，请核对版本后继续。');
      } else {
        snapshot.onVersionRestored?.(chapter);
        setRevisionOpen(false);
      }
      setRefresh((value) => value + 1);
      if (historyOpen) await loadHistory();
    } catch (failure) { if (!controller.signal.aborted) setRevisionError(errorText(failure)); }
    finally { operations.current.delete(controller); mutation.current = null; if (!controller.signal.aborted) setRestoring(false); }
  };

  const cancel = async () => {
    if (!data?.job || mutation.current) return;
    const controller = new AbortController(); mutation.current = controller; operations.current.add(controller);
    setCancelling(true); setError('');
    try {
      const job = await chapterMemoryApi.cancelJob(data.job.id, controller.signal);
      if (controller.signal.aborted) return;
      setData((previous) => previous ? { ...previous, job } : previous);
      setRefresh((value) => value + 1);
    } catch (failure) { if (!controller.signal.aborted) setError(errorText(failure)); }
    finally { operations.current.delete(controller); mutation.current = null; if (!controller.signal.aborted) setCancelling(false); }
  };

  const digest = data?.digest;
  const stale = data?.status === 'stale' || Boolean(digest && digest.source_version < Math.max(currentVersion, data?.current_version ?? 0));
  const groups = digest ? [
    { label: '出场人物', items: digest.participants },
    { label: '提取事件', items: digest.events },
    { label: '状态变化候选（未确认为设定）', items: digest.state_change_candidates },
    { label: '未解线索', items: digest.open_threads },
  ] : [];

  return <Stack spacing={1.5}>
    <Typography variant="caption" color="text.secondary">基于已保存版本 v{Math.max(currentVersion, data?.current_version ?? 0)}。重建只读取已保存正文，不会保存当前编辑稿。</Typography>
    {error && <Alert severity="warning">{error}</Alert>}
    {!data && !error && <Typography role="status">正在读取章节记忆…</Typography>}
    {data && <>
      {!data.worker_enabled && <Alert severity="info">自动提取未启用；提取任务会保留在队列中。</Alert>}
      {isPending(data) && <Typography role="status">{data.job?.state === 'running' ? '正在提取简介…' : '简介等待提取'}</Typography>}
      {data.job?.state === 'failed' && <Alert severity="warning">简介提取失败：{data.job.error_message || '请稍后重建重试'}</Alert>}
      {data.job?.state === 'cancelled' && <Alert severity="info">简介提取已取消，可在需要时重新排队。</Alert>}
      {stale && <Alert severity="warning">简介已过期，以下内容来自旧版本。</Alert>}
      {!digest && <Typography variant="body2">当前还没有可用简介。</Typography>}
      {digest && <>
        <Typography variant="subtitle2">提取简介 · 来源版本 v{digest.source_version}</Typography>
        <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{digest.summary}</Typography>
        {groups.filter((group) => group.items.length > 0).map((group) => <Box key={group.label}>
          <Typography variant="caption" color="text.secondary">{group.label}</Typography>
          {group.items.map((item, index) => <Typography variant="body2" key={index} sx={{ overflowWrap: 'anywhere' }}>· {item}</Typography>)}
        </Box>)}
        <Button size="small" onClick={() => void viewRevision(digest.source_revision_id)}>查看简介来源原文</Button>
        {digest.source_refs.map((source, index) => <Box key={`${source.revision_id}-${index}`} sx={{ borderLeft: 2, borderColor: 'divider', pl: 1 }}>
          <Typography variant="caption" sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{source.quote}</Typography>
        </Box>)}
      </>}
    </>}
    {pollStopped && <Alert severity="info">本次自动刷新已暂停，任务仍可在后台继续。可手动刷新查看进度。</Alert>}
    <Stack direction="row" spacing={1} flexWrap="wrap">
      <Button size="small" onClick={() => setRefresh((value) => value + 1)}>刷新记忆</Button>
      <Button size="small" disabled={!data || rebuilding || isPending(data)} onClick={() => void rebuild()}>{rebuilding ? '正在排队…' : '重建简介'}</Button>
      {data && isPending(data) && <Button size="small" disabled={cancelling} onClick={() => void cancel()}>{cancelling ? '正在取消…' : '取消简介提取'}</Button>}
      <Button size="small" disabled={historyLoading} onClick={() => void loadHistory()}>查看原文历史</Button>
    </Stack>
    {historyOpen && <Box>
      <Typography variant="subtitle2">已保存原文版本</Typography>
      <Typography variant="caption" color="text.secondary">历史从版本记录启用后保留，早期编辑过程无法补回。</Typography>
      {revisions.map((item) => <Button key={item.id} fullWidth size="small" sx={{ justifyContent: 'flex-start' }} onClick={() => void viewRevision(item.id)}>
        v{item.version} · {item.title}
      </Button>)}
      {historyLoading ? <Typography role="status">正在读取原文历史…</Typography> : revisions.length === 0 && <Typography variant="body2">暂无原文历史。</Typography>}
      {hasMore && <Button size="small" disabled={historyLoading} onClick={() => void loadHistory(revisions.at(-1)?.version)}>加载更早版本</Button>}
    </Box>}
    <Dialog open={revisionOpen} fullWidth maxWidth="md" onClose={() => { if (!restoring) { revisionController.current?.abort(); setRevisionOpen(false); } }}>
      <DialogTitle>{revision ? `原文版本 v${revision.version} · ${revision.title}` : '原文版本'}</DialogTitle>
      <DialogContent dividers>
        {revisionError && <Alert severity="warning">{revisionError}</Alert>}
        {revision ? <>
          <Typography variant="caption" color="text.secondary">这是保留的原文快照。恢复会建立一个新版本，历史原文仍保留。</Typography>
          <Typography component="pre" sx={{ fontFamily: 'inherit', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{revision.content || '（空正文）'}</Typography>
          {props.onVersionRestored && !props.canRestore && <Alert severity="info">请先保存当前正文并完成身份核验，再恢复历史版本。</Alert>}
          {restoreConfirm && <Alert severity="warning">确认将本章标题和正文恢复为 v{revision.version} 的内容，并保存为新版本。</Alert>}
        </> : !revisionError && <Typography role="status">正在读取来源原文…</Typography>}
      </DialogContent>
      <DialogActions>
        {revision && props.onVersionRestored && <Button variant={restoreConfirm ? 'contained' : 'text'} disabled={!props.canRestore || restoring || revision.chapter_id !== chapterId} onClick={() => { if (restoreConfirm) void restore(); else setRestoreConfirm(true); }}>{restoring ? '正在恢复…' : restoreConfirm ? '确认恢复并保存' : '恢复为新版本'}</Button>}
        <Button disabled={restoring} onClick={() => { revisionController.current?.abort(); setRevisionOpen(false); }}>关闭原文</Button>
      </DialogActions>
    </Dialog>
  </Stack>;
}

export default function ChapterMemory(props: Props) {
  const [expanded, setExpanded] = useState(false);
  return <Accordion disableGutters expanded={expanded} onChange={(_event, value) => setExpanded(value)} sx={{ mb: 2, boxShadow: 'none' }}>
    <AccordionSummary expandIcon={<ExpandMoreIcon />}><Typography variant="body2">章节记忆</Typography></AccordionSummary>
    <AccordionDetails>
      {expanded && (props.chapterId === null ? <Typography variant="body2">请先选择章节。</Typography> : <MemoryDetails key={`${props.novelId}-${props.novelLifecycleId}-${props.chapterId}-${props.chapterLifecycleId}`} {...props} chapterId={props.chapterId} />)}
    </AccordionDetails>
  </Accordion>;
}
