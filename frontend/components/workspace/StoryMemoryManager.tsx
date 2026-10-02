'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Box, Button, Card, CardContent, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Stack, Tab, Tabs, TextField, Typography } from '@mui/material';
import { StatusChip } from '@/components/common/primitives';
import { storyMemoryApi, storyEntityLabel } from '@/lib/storyMemory';
import { chapterMemoryApi } from '@/lib/chapterMemory';
import type { ChapterRevision } from '@/types/chapterMemory';
import type { MemorySource, StoryMemorySnapshot } from '@/types/storyMemory';
import MemoryEditorDialog, { type MemoryEditor, type MemoryOperation } from './MemoryEditorDialog';

interface Props { novelId: number; novelLifecycleId: string; chapterId: number | null; chapterNumber: number | null }
const entityLabels = { character: '人物', item: '物品', location: '地点', organization: '组织' };
const attributeLabels: Record<string, string> = { owner: '所有者', holder: '持有者', quantity: '数量' };
const candidateLabels = { pending: '待审阅', confirmed: '已确认', rejected: '已拒绝', revoked: '已撤销' };
/** 批1 状态章语义：待审阅中性实心、已确认绿实心、已拒绝/已撤销灰描边（正常裁决非错误）；来源未确认走琥珀描边。 */
const candidateTones: Record<string, 'pending' | 'success' | 'rejected'> = { pending: 'pending', confirmed: 'success', rejected: 'rejected', revoked: 'rejected' };
const sourceLabel = (status: string) => status === 'ready' ? '来源有效' : '原文已变化，待重核';

function MemoryWorkspace({ novelId, novelLifecycleId, chapterId, chapterNumber }: Props) {
  const [data, setData] = useState<StoryMemorySnapshot | null>(null);
  const [tab, setTab] = useState<'outline' | 'entities' | 'candidates'>('outline');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [editor, setEditor] = useState<MemoryEditor | null>(null);
  const [editorSequence, setEditorSequence] = useState(0);
  const [asOf, setAsOf] = useState<number | undefined>(chapterNumber ?? undefined);
  const [chapterInput, setChapterInput] = useState(String(chapterNumber ?? ''));
  const [selectedEntity, setSelectedEntity] = useState('');
  const [history, setHistory] = useState(false);
  const [sourceOpen, setSourceOpen] = useState(false);
  const [sourceRevision, setSourceRevision] = useState<ChapterRevision | null>(null);
  const [sourceError, setSourceError] = useState('');
  const active = useRef(true);
  const operations = useRef(new Set<AbortController>());
  const readController = useRef<AbortController | null>(null);
  const sourceController = useRef<AbortController | null>(null);
  const busyRef = useRef(false);

  useEffect(() => {
    active.current = true;
    const requests = operations.current;
    return () => { active.current = false; requests.forEach((controller) => controller.abort()); };
  }, []);
  const load = useCallback(async () => {
    readController.current?.abort();
    const controller = new AbortController();
    readController.current = controller; operations.current.add(controller);
    setLoading(true);
    try {
      const result = await storyMemoryApi.get(novelId, asOf, controller.signal);
      if (controller.signal.aborted || !active.current) return;
      if (result.novel_lifecycle_id !== novelLifecycleId) throw new Error('作品已删除重建，请重新打开当前作品。');
      setData(result);
    } catch (failure) {
      if (!controller.signal.aborted && active.current) setError(failure instanceof Error ? failure.message : '读取结构化记忆失败');
    } finally { operations.current.delete(controller); if (!controller.signal.aborted && active.current) setLoading(false); }
  }, [novelId, novelLifecycleId, asOf]);
  useEffect(() => { setError(''); void load(); return () => readController.current?.abort(); }, [load]);
  useEffect(() => { setAsOf(chapterNumber ?? undefined); setChapterInput(String(chapterNumber ?? '')); }, [chapterNumber]);

  const open = (next: MemoryEditor) => { setError(''); setEditorSequence((value) => value + 1); setEditor(next); };
  const mutate = async (operation: MemoryOperation, requestId: string) => {
    if (!data || busyRef.current) return;
    const controller = new AbortController(); operations.current.add(controller);
    readController.current?.abort(); busyRef.current = true; setBusy(true); setError('');
    try {
      const result = await operation({ request_id: requestId, expected_version: data.version, novel_lifecycle_id: data.novel_lifecycle_id }, controller.signal);
      if (controller.signal.aborted || !active.current) return;
      if (result.novel_lifecycle_id !== novelLifecycleId) throw new Error('作品身份已经变化，请重新打开。');
      setData(result); setEditor(null);
      await load();
    } catch (failure) {
      if (!controller.signal.aborted && active.current) {
        const status = typeof failure === 'object' && failure !== null && 'status' in failure ? failure.status : null;
        if (status === 409) { await load(); if (active.current) setError('记忆已被其他操作更新。已刷新，请重新核对后提交；填写内容仍保留。'); }
        else setError(failure instanceof Error ? failure.message : '保存失败，填写内容已保留');
      }
    } finally { operations.current.delete(controller); busyRef.current = false; if (active.current) setBusy(false); }
  };
  const closeSource = () => { sourceController.current?.abort(); setSourceOpen(false); setSourceRevision(null); };
  const viewSource = async (source: MemorySource) => {
    sourceController.current?.abort();
    const controller = new AbortController(); sourceController.current = controller; operations.current.add(controller);
    setSourceOpen(true); setSourceRevision(null); setSourceError('');
    try {
      const revision = await chapterMemoryApi.getRevision(novelId, source.revision_id, controller.signal);
      if (controller.signal.aborted || !active.current) return;
      if (revision.id !== source.revision_id || (source.content_hash && revision.content_hash !== source.content_hash) || Array.from(revision.content).slice(source.start, source.start + Array.from(source.quote).length).join('') !== source.quote) throw new Error('来源引用与原文不一致，暂不能展示。');
      setSourceRevision(revision);
    } catch (failure) { if (!controller.signal.aborted && active.current) setSourceError(failure instanceof Error ? failure.message : '来源不可用，可能已删除'); }
    finally { operations.current.delete(controller); }
  };
  const refs = (sources: MemorySource[]) => sources.length > 0 && <Stack spacing={0.5} sx={{ mt: 1 }}>{sources.map((source, index) => <Box key={`${source.revision_id}-${index}`}>
    <Typography variant="caption" sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>引用：{source.quote}</Typography>
    <Button size="small" onClick={() => void viewSource(source)}>查看来源原文</Button>
  </Box>)}</Stack>;
  return <Box sx={{ my: 3 }}>
    <Stack direction="row" alignItems="center" justifyContent="space-between" gap={1} sx={{ mb: 1 }}>
      <Typography variant="h6">大纲与人物物品记忆</Typography>
      <Button disabled={busy || loading} onClick={() => { setError(''); void load(); }}>刷新记忆</Button>
    </Stack>
    <Typography variant="body2" color="text.secondary">计划、已发生剧情和人物物品状态分别维护。AI 提取内容保留出处，变化候选须由你确认。</Typography>
    {error && !editor && <Alert severity="warning" sx={{ my: 1 }}>{error}</Alert>}
    {loading && <Typography role="status">正在读取记忆…</Typography>}
    {data && <>
      {data.warnings.map((warning, index) => <Alert severity="info" key={index} sx={{ my: 1 }}>{warning}</Alert>)}
      <Tabs value={tab} onChange={(_event, value) => setTab(value)} aria-label="结构化记忆分类">
        <Tab value="outline" label="计划与实际大纲" /><Tab value="entities" label="人物与物品" /><Tab value="candidates" label={`变化候选（${data.candidates.filter((x) => x.status === 'pending').length}）`} />
      </Tabs>
      {tab === 'outline' && <>
        <Stack direction="row" gap={1} sx={{ my: 2 }}><Button disabled={busy} variant="outlined" onClick={() => open({ kind: 'outline' })}>新增大纲</Button><Button disabled={busy || chapterId === null} onClick={() => open({ kind: 'extract' })}>从当前章提取候选</Button></Stack>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' }, gap: 2 }}>
          {(['planned', 'occurred'] as const).map((status) => <Stack spacing={1} key={status}>
            <Typography variant="subtitle1">{status === 'planned' ? '作者计划' : '已发生剧情'}</Typography>
            {data.outline_nodes.filter((node) => node.plot_status === status).length === 0 && <Typography variant="body2" color="text.secondary">暂无{status === 'planned' ? '计划' : '实际'}大纲。</Typography>}
            {data.outline_nodes.filter((node) => node.plot_status === status).map((node) => <Card variant="outlined" key={node.id}><CardContent>
              <Typography variant="subtitle2">{node.title}</Typography>
              <Typography variant="caption">{node.kind === 'volume' ? '卷' : node.kind === 'chapter' ? '章' : '场景'}{node.chapter_number ? ` · 第 ${node.chapter_number} 章` : ''}{node.parent_id ? ` · 上级：${data.outline_nodes.find((x) => x.id === node.parent_id)?.title ?? '不可用'}` : ''}</Typography>
              <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>冲突：{node.conflict || '未填写'}</Typography>
              <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>{status === 'planned' ? '预期结果' : '结果'}：{node.outcome || '未填写'}</Typography>
              <Stack direction="row" gap={1} flexWrap="wrap">
                {/* 属性来源与状态语义分章（走查 Top1 连坐拆分）：属性=neutral 描边、来源有效=success 描边、待重核=琥珀描边 */}
                <StatusChip size="small" tone="neutral" label={node.origin === 'ai' ? 'AI 提取参考' : '作者维护'} />
                <StatusChip size="small" tone={node.source_status === 'ready' ? 'achieved' : 'stale'} label={sourceLabel(node.source_status)} />
              </Stack>
              {refs(node.source_refs)}
              <Stack direction="row" gap={1} sx={{ mt: 1 }}><Button size="small" disabled={busy} onClick={() => open({ kind: 'outline', outline: node })}>编辑{node.title}</Button>{node.source_status !== 'ready' && <Button size="small" disabled={busy} onClick={() => open({ kind: 'resolve', outline: node })}>重新核对来源</Button>}</Stack>
            </CardContent></Card>)}
          </Stack>)}
        </Box>
      </>}
      {tab === 'entities' && <Stack spacing={2} sx={{ my: 2 }}>
        <Stack direction="row" flexWrap="wrap" gap={1}>
          <Button variant="outlined" disabled={busy} onClick={() => open({ kind: 'entity' })}>新增人物或物品</Button>
          <Button disabled={busy || data.entities.length === 0} onClick={() => open({ kind: 'state', entity: data.entities.find((x) => x.id === selectedEntity) })}>记录确认状态</Button>
          <Button disabled={busy || data.entities.length === 0 || chapterId === null} onClick={() => open({ kind: 'candidate', entity: data.entities.find((x) => x.id === selectedEntity) })}>提交状态候选</Button>
        </Stack>
        <TextField select label="查看实体" value={selectedEntity} onChange={(event) => setSelectedEntity(event.target.value)}>
          <MenuItem value="">全部实体</MenuItem>{data.entities.map((entity, index) => <MenuItem key={entity.id} value={entity.id}>{storyEntityLabel(entity)} · {entityLabels[entity.kind]} · {index + 1}</MenuItem>)}
        </TextField>
        {data.entities.length === 0 && <Typography>暂无实体，请先建立人物或物品。</Typography>}
        <Stack direction="row" alignItems="center" flexWrap="wrap" gap={1}>
          <TextField size="small" label="查看截至章节（留空看最新）" value={chapterInput} disabled={busy} onChange={(event) => setChapterInput(event.target.value)} />
          <Button disabled={busy} onClick={() => {
            const value = chapterInput.trim() ? Number(chapterInput) : undefined;
            if (value !== undefined && (!Number.isInteger(value) || value < 1)) { setError('查看章节必须是大于 0 的整数'); return; }
            setError(''); setAsOf(value);
          }}>查看状态</Button>
          <Button onClick={() => setHistory((value) => !value)}>{history ? '显示当前状态' : '显示状态历史'}</Button>
        </Stack>
        <Typography variant="subtitle2">{history ? '全部状态历史（包括已撤销）' : asOf ? `截至第 ${asOf} 章的状态` : '最新状态'}</Typography>
        {(history ? data.state_history : data.states).filter((state) => !selectedEntity || state.entity_id === selectedEntity).map((state) => <Card variant="outlined" key={state.id}><CardContent>
          <Typography variant="subtitle2">{data.entities.find((x) => x.id === state.entity_id) ? storyEntityLabel(data.entities.find((x) => x.id === state.entity_id)) : state.subject} · {attributeLabels[state.attribute] ?? state.attribute}</Typography>
          <Typography sx={{ whiteSpace: 'pre-wrap' }}>{state.value}{state.value_entity_id ? `（关联：${storyEntityLabel(data.entities.find((x) => x.id === state.value_entity_id))}）` : ''}</Typography>
          <Typography variant="caption">{state.chapter_established ? `第 ${state.chapter_established} 章生效` : '全书有效'}{state.retired_chapter ? ` · 第 ${state.retired_chapter} 章起失效` : ''}{state.status === 'revoked' ? ' · 已撤销' : ''}</Typography>
          <Box><StatusChip size="small" tone={state.source_status === 'ready' ? 'achieved' : 'stale'} label={sourceLabel(state.source_status)} /></Box>
          {refs(state.source_refs)}
          <Stack direction="row" gap={1}><Button size="small" disabled={busy || state.status === 'revoked'} onClick={() => open({ kind: 'state', state })}>修正状态</Button>{state.source_status !== 'ready' && <Button size="small" disabled={busy || state.status === 'revoked'} onClick={() => open({ kind: 'resolve', state })}>重新核对来源</Button>}</Stack>
        </CardContent></Card>)}
        {(history ? data.state_history : data.states).filter((state) => !selectedEntity || state.entity_id === selectedEntity).length === 0 && <Typography variant="body2">此范围暂无状态记录。</Typography>}
      </Stack>}
      {tab === 'candidates' && <Stack spacing={2} sx={{ my: 2 }}>
        <Button disabled={busy || chapterId === null} onClick={() => open({ kind: 'extract' })}>从当前章提取候选</Button>
        {data.candidates.length === 0 && <Typography>暂无变化候选。可从原文提取，或在人物与物品中提交带出处的候选。</Typography>}
        {data.candidates.map((candidate) => <Card variant="outlined" key={candidate.id}><CardContent>
          <Typography variant="subtitle2">{storyEntityLabel(data.entities.find((x) => x.id === candidate.entity_id))} · {attributeLabels[candidate.attribute] ?? candidate.attribute}</Typography>
          <Typography sx={{ whiteSpace: 'pre-wrap' }}>{candidate.value}</Typography>
          <Typography variant="caption">从第 {candidate.effective_chapter} 章生效</Typography>
          <Stack direction="row" flexWrap="wrap" gap={1}><StatusChip tone={candidateTones[candidate.status] ?? 'neutral'} label={candidateLabels[candidate.status] ?? candidate.status} /><StatusChip size="small" tone={candidate.source_status === 'ready' ? 'achieved' : 'stale'} label={sourceLabel(candidate.source_status)} /></Stack>
          {candidate.reason && <Typography variant="body2">审阅理由：{candidate.reason}</Typography>}
          {refs(candidate.source_refs)}
          {candidate.status === 'pending' && <Stack direction="row" gap={1} sx={{ mt: 1 }}>
            <Button disabled={busy || candidate.source_status !== 'ready'} onClick={() => open({ kind: 'decision', candidate, action: 'confirm' })}>审阅并确认</Button>
            <Button disabled={busy} color="inherit" onClick={() => open({ kind: 'decision', candidate, action: 'reject' })}>拒绝候选</Button>
          </Stack>}
          {candidate.status === 'pending' && candidate.source_status !== 'ready' && <Typography variant="caption" color="warning.main">来源已变化，不能直接确认；请基于新原文重新提取或提交候选。</Typography>}
          {candidate.status === 'confirmed' && <Button disabled={busy} color="warning" onClick={() => open({ kind: 'decision', candidate, action: 'revoke' })}>撤销确认</Button>}
        </CardContent></Card>)}
      </Stack>}
      {editor && <MemoryEditorDialog key={editorSequence} novelId={novelId} chapterId={chapterId} chapterNumber={chapterNumber} snapshot={data} editor={editor} busy={busy} error={error} onClose={() => { setEditor(null); setError(''); }} onSave={mutate} />}
    </>}
    <Dialog open={sourceOpen} fullWidth maxWidth="md" onClose={closeSource}>
      <DialogTitle>{sourceRevision ? `来源原文 · ${sourceRevision.title} · v${sourceRevision.version}` : '来源原文'}</DialogTitle>
      <DialogContent dividers>{sourceError ? <Alert severity="warning">{sourceError}</Alert> : sourceRevision ? <>
        <Typography variant="caption">只读历史原文；后续改稿不会改变这份版本。</Typography>
        <Typography component="pre" sx={{ fontFamily: 'inherit', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{sourceRevision.content}</Typography>
      </> : <Typography role="status">正在读取来源原文…</Typography>}</DialogContent>
      <DialogActions><Button onClick={closeSource}>关闭原文</Button></DialogActions>
    </Dialog>
  </Box>;
}
export default function StoryMemoryManager(props: Props) {
  return <MemoryWorkspace key={`${props.novelId}-${props.novelLifecycleId}`} {...props} />;
}
