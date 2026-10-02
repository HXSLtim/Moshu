'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Box, Button, Card, CardContent, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Stack, Tab, Tabs, TextField, Typography } from '@mui/material';
import { StatusChip } from '@/components/common/primitives';
import { api } from '@/lib/api';
import type { StoryEvent, StoryFact } from '@/types/storyBible';

type Kind = 'facts' | 'events';
type Entry = StoryFact | StoryEvent;
interface Editor {
  entry: Entry | null;
  subject: string;
  attribute: string;
  value: string;
  description: string;
  chapter: string;
  retiredChapter: string;
  storyDay: string;
  characters: string;
  foreshadowing: string;
  status: string;
}
const PAGE_SIZE = 20;
const statusLabels: Record<string, string> = { active: '有效', retired: '已失效', planned: '计划中', occurred: '已发生' };
/** 批1 状态章语义：色+文字双通道，账本四态不再全灰；未知历史值回中性档。 */
const statusTones: Record<string, 'success' | 'stale' | 'planned' | 'achieved'> = { active: 'success', retired: 'stale', planned: 'planned', occurred: 'achieved' };

function newEditor(entry: Entry | null, kind: Kind): Editor {
  const fact = entry && 'subject' in entry ? entry : null;
  const event = entry && 'title' in entry ? entry : null;
  return {
    entry, subject: fact?.subject ?? event?.title ?? '', attribute: fact?.attribute ?? '',
    value: fact?.value ?? '', description: entry?.description ?? '',
    chapter: String(fact?.chapter_established ?? event?.chapter ?? ''),
    retiredChapter: String(fact?.retired_chapter ?? ''), storyDay: String(event?.story_day ?? 1),
    characters: event?.involved_characters.join('、') ?? '', foreshadowing: event?.foreshadowing ?? '',
    status: entry?.status ?? (kind === 'facts' ? 'active' : 'planned'),
  };
}

function optionalChapter(value: string): number | null {
  if (!value.trim()) return null;
  const number = Number(value);
  if (!Number.isInteger(number) || number < 1) throw new Error('章节号必须是大于 0 的整数');
  return number;
}

function StoryBibleSection({ novelId, kind }: { novelId: number; kind: Kind }) {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [nextSkip, setNextSkip] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [editor, setEditor] = useState<Editor | null>(null);
  const [deleting, setDeleting] = useState<Entry | null>(null);
  const [saving, setSaving] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);
  const label = kind === 'facts' ? '设定事实' : '剧情事件';

  const load = useCallback(async (skip: number) => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setLoading(true);
    setError('');
    try {
      const result = kind === 'facts'
        ? await api.listStoryFacts(novelId, skip, PAGE_SIZE, { signal: controller.signal })
        : await api.listStoryEvents(novelId, skip, PAGE_SIZE, { signal: controller.signal });
      if (controller.signal.aborted) return;
      setEntries((previous) => skip === 0 ? result : [...previous, ...result]);
      setNextSkip(skip + result.length);
      setHasMore(result.length === PAGE_SIZE);
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : '读取设定失败');
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [kind, novelId]);

  useEffect(() => {
    void load(0);
    return () => controllerRef.current?.abort();
  }, [load]);

  const save = async () => {
    if (!editor || saving) return;
    setError('');
    setSaving(true);
    try {
      const chapter = optionalChapter(editor.chapter);
      if (kind === 'facts') {
        if (!editor.subject.trim() || !editor.attribute.trim() || !editor.value.trim()) throw new Error('请填写主体、属性和事实内容');
        const data = { value: editor.value.trim(), description: editor.description, chapter_established: chapter };
        if (editor.entry) {
          const retired = editor.status === 'retired' ? optionalChapter(editor.retiredChapter) : null;
          if (retired !== null && chapter !== null && retired < chapter) throw new Error('失效章节不能早于确立章节');
          await api.updateStoryFact(editor.entry.id, { ...data, status: editor.status as StoryFact['status'], retired_chapter: retired });
        } else {
          await api.createStoryFact({ ...data, novel_id: novelId, subject: editor.subject.trim(), attribute: editor.attribute.trim() });
        }
      } else {
        if (!editor.subject.trim() || !editor.description.trim()) throw new Error('请填写事件标题和描述');
        const storyDay = Number(editor.storyDay);
        if (!Number.isInteger(storyDay) || storyDay < 1) throw new Error('故事天数必须是大于 0 的整数');
        const characters = editor.characters.split(/[、,，\n]/).map((name) => name.trim()).filter(Boolean);
        if (characters.length > 50 || characters.some((name) => name.length > 100)) throw new Error('最多关联 50 个角色，每个名字不超过 100 字');
        const data = { title: editor.subject.trim(), description: editor.description.trim(), story_day: storyDay, chapter,
          involved_characters: characters, foreshadowing: editor.foreshadowing, status: editor.status as StoryEvent['status'] };
        if (editor.entry) await api.updateStoryEvent(editor.entry.id, data);
        else await api.createStoryEvent({ ...data, novel_id: novelId });
      }
      setEditor(null);
      await load(0);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '保存失败，填写内容已保留');
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!deleting || saving) return;
    setSaving(true);
    setError('');
    try {
      if (kind === 'facts') await api.deleteStoryFact(deleting.id);
      else await api.deleteStoryEvent(deleting.id);
      setDeleting(null);
      await load(0);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '删除失败');
    } finally { setSaving(false); }
  };

  const field = (key: keyof Omit<Editor, 'entry'>, title: string, maxLength: number, multiline = false) => (
    <TextField fullWidth label={title} value={editor?.[key] ?? ''} multiline={multiline} minRows={multiline ? 3 : undefined}
      disabled={saving || (kind === 'facts' && Boolean(editor?.entry) && (key === 'subject' || key === 'attribute'))}
      slotProps={{ htmlInput: { maxLength } }}
      onChange={(event) => setEditor((previous) => previous && { ...previous, [key]: event.target.value })} />
  );

  return <Box sx={{ py: 2 }}>
    <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ xs: 'stretch', sm: 'center' }} gap={2} sx={{ mb: 2 }}>
      <Typography variant="body2" color="text.secondary">{kind === 'facts' ? '记录人物、地点与世界规则，供后续创作参考。' : '整理事件顺序、参与人物和伏笔。'}</Typography>
      <Button variant="contained" sx={{ flexShrink: 0 }} onClick={() => { setError(''); setEditor(newEditor(null, kind)); }}>新增{label}</Button>
    </Stack>
    {error && !editor && !deleting && <Alert severity="error" sx={{ mb: 2 }} action={<Button color="inherit" onClick={() => void load(0)}>重试</Button>}>{error}</Alert>}
    {loading && <Typography role="status">正在读取{label}…</Typography>}
    {!loading && !error && entries.length === 0 && <Alert severity="info">还没有{label}，可以先添加一条。</Alert>}
    <Stack spacing={2}>
      {entries.map((entry) => <Card key={entry.id} variant="outlined"><CardContent>
        <Stack direction="row" justifyContent="space-between" gap={2}>
          <Typography variant="h6">{'subject' in entry ? `${entry.subject} · ${entry.attribute}` : entry.title}</Typography>
          <StatusChip tone={statusTones[entry.status] ?? 'neutral'} label={statusLabels[entry.status] ?? entry.status} />
        </Stack>
        <Typography sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', my: 1 }}>{'value' in entry ? entry.value : entry.description}</Typography>
        {'subject' in entry ? <>
          {entry.description && <Typography variant="body2" color="text.secondary">{entry.description}</Typography>}
          <Typography variant="caption">{entry.chapter_established ? `第 ${entry.chapter_established} 章确立` : '全书通用设定'}{entry.retired_chapter ? ` · 第 ${entry.retired_chapter} 章失效` : ''}</Typography>
        </> : <>
          <Typography variant="caption">故事第 {entry.story_day} 天{entry.chapter ? ` · 第 ${entry.chapter} 章` : ''}{entry.involved_characters.length ? ` · ${entry.involved_characters.join('、')}` : ''}</Typography>
          {entry.foreshadowing && <Typography variant="body2" sx={{ mt: 1 }}>伏笔：{entry.foreshadowing}</Typography>}
        </>}
        <Stack direction="row" gap={1} sx={{ mt: 1 }}>
          <Button size="small" aria-label={`编辑${'subject' in entry ? entry.subject : entry.title}`} onClick={() => { setError(''); setEditor(newEditor(entry, kind)); }}>编辑</Button>
          <Button size="small" color="error" aria-label={`删除${'subject' in entry ? entry.subject : entry.title}`} onClick={() => { setError(''); setDeleting(entry); }}>删除</Button>
        </Stack>
      </CardContent></Card>)}
    </Stack>
    {hasMore && <Button sx={{ mt: 2 }} disabled={loading} onClick={() => void load(nextSkip)}>加载更多{label}</Button>}
    <Dialog open={Boolean(editor)} onClose={() => { if (!saving) setEditor(null); }} fullWidth maxWidth="sm">
      <DialogTitle>{editor?.entry ? '编辑' : '新增'}{label}</DialogTitle>
      <DialogContent><Stack spacing={2} sx={{ pt: 1 }}>
        {error && <Alert severity="error">{error}</Alert>}
        {field('subject', kind === 'facts' ? '主体（人物、地点或组织）' : '事件标题', kind === 'facts' ? 100 : 200)}
        {kind === 'facts' && <>{field('attribute', '属性（如身份、位置）', 100)}{field('value', '事实内容', 2000, true)}</>}
        {field('description', kind === 'facts' ? '补充说明' : '事件描述', kind === 'facts' ? 4000 : 8000, true)}
        {field('chapter', kind === 'facts' ? '确立章节（可留空）' : '对应章节（可留空）', 9)}
        {(kind === 'events' || editor?.entry) && <TextField select label="状态" value={editor?.status ?? ''} disabled={saving}
          onChange={(event) => setEditor((previous) => previous && { ...previous, status: event.target.value })}>
          {(kind === 'facts' ? ['active', 'retired'] : ['planned', 'occurred']).map((status) => <MenuItem key={status} value={status}>{statusLabels[status]}</MenuItem>)}
        </TextField>}
        {kind === 'facts' && editor?.status === 'retired' && field('retiredChapter', '失效章节（可留空）', 9)}
        {kind === 'events' && <>{field('storyDay', '故事第几天', 9)}{field('characters', '关联角色（用顿号分隔）', 5050)}{field('foreshadowing', '伏笔或线索', 4000, true)}</>}
        <Typography variant="caption" color="text.secondary">保存后成为正式设定，仅记录你已确认的内容。</Typography>
      </Stack></DialogContent>
      <DialogActions><Button disabled={saving} onClick={() => setEditor(null)}>取消</Button><Button variant="contained" disabled={saving} onClick={() => void save()}>{saving ? '保存中…' : '保存设定'}</Button></DialogActions>
    </Dialog>
    <Dialog open={Boolean(deleting)} onClose={() => { if (!saving) setDeleting(null); }}>
      <DialogTitle>删除{label}</DialogTitle><DialogContent>
        {error && <Alert severity="error">{error}</Alert>}
        <Typography>确定删除「{deleting && ('subject' in deleting ? `${deleting.subject} · ${deleting.attribute}` : deleting.title)}」？{kind === 'facts' ? '如果它只是随剧情失效，可以改为“已失效”以保留记录。' : ''}</Typography>
      </DialogContent><DialogActions><Button disabled={saving} onClick={() => setDeleting(null)}>取消</Button><Button color="error" disabled={saving} onClick={() => void remove()}>确认删除</Button></DialogActions>
    </Dialog>
  </Box>;
}

export default function StoryBibleManager({ novelId }: { novelId: number }) {
  const [kind, setKind] = useState<Kind>('facts');
  return <>
    <Tabs value={kind} onChange={(_event, value: Kind) => setKind(value)} aria-label="设定账本分类">
      <Tab value="facts" label="设定事实" /><Tab value="events" label="剧情与伏笔" />
    </Tabs>
    <StoryBibleSection key={`${novelId}:${kind}`} novelId={novelId} kind={kind} />
  </>;
}
