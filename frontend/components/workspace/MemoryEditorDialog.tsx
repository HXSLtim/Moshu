'use client';

import { useCallback, useRef, useState } from 'react';
import { Alert, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, MenuItem, Stack, TextField, Typography } from '@mui/material';
import { storyMemoryApi, storyEntityLabel } from '@/lib/storyMemory';
import type { EntityState, MemoryCommand, MemorySource, OutlineNode, StateCandidate, StoryEntity, StoryMemorySnapshot } from '@/types/storyMemory';
import MemorySourcePicker from './MemorySourcePicker';

export interface MemoryEditor {
  kind: 'entity' | 'outline' | 'state' | 'candidate' | 'decision' | 'resolve' | 'extract';
  entity?: StoryEntity; outline?: OutlineNode; state?: EntityState; candidate?: StateCandidate;
  action?: 'confirm' | 'reject' | 'revoke';
}
export type MemoryOperation = (command: MemoryCommand, signal: AbortSignal) => Promise<StoryMemorySnapshot>;
interface Props {
  novelId: number; chapterId: number | null; chapterNumber: number | null; snapshot: StoryMemorySnapshot;
  editor: MemoryEditor; busy: boolean; error: string; onClose: () => void; onSave: (operation: MemoryOperation, requestId: string) => Promise<void>;
}
const entityLabels = { character: '人物', item: '物品', location: '地点', organization: '组织' };
const actionLabels = { confirm: '确认候选', reject: '拒绝候选', revoke: '撤销确认' };
const positive = (value: string) => {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1) throw new Error('生效或对应章节必须是大于 0 的整数');
  return parsed;
};

export default function MemoryEditorDialog({ novelId, chapterId, chapterNumber, snapshot, editor, busy, error, onClose, onSave }: Props) {
  const [values, setValues] = useState<Record<string, string>>({
    name: '', description: '', kind: editor.outline?.kind ?? 'scene', entityKind: 'character', parentId: editor.outline?.parent_id ?? '',
    plotStatus: editor.outline?.plot_status ?? 'planned', chapter: String(editor.outline?.chapter_number ?? chapterNumber ?? ''),
    title: editor.outline?.title ?? '', conflict: editor.outline?.conflict ?? '', outcome: editor.outline?.outcome ?? '',
    entityId: editor.entity?.id ?? editor.state?.entity_id ?? snapshot.entities[0]?.id ?? '',
    attribute: editor.state?.attribute ?? ((editor.entity ?? snapshot.entities[0])?.kind === 'item' ? 'holder' : ''), value: editor.state?.value ?? '',
    valueEntityId: editor.state?.value_entity_id ?? '', effectiveChapter: String(editor.state?.chapter_established ?? chapterNumber ?? 1), reason: '',
  });
  const [withSource, setWithSource] = useState(editor.kind === 'candidate' || editor.kind === 'extract');
  const [source, setSource] = useState<MemorySource | null>(null);
  const [revisionId, setRevisionId] = useState<string | null>(null);
  const attempt = useRef<{ key: string; id: string } | null>(null);
  const [validation, setValidation] = useState('');
  const sourceChanged = useCallback((next: MemorySource | null, id: string | null) => { setSource(next); setRevisionId(id); }, []);
  const field = (key: string, label: string, multiline = false, maxLength = 2000) => <TextField label={label} value={values[key]} disabled={busy} multiline={multiline} minRows={multiline ? 2 : undefined} slotProps={{ htmlInput: { maxLength } }} onChange={(event) => setValues((old) => ({ ...old, [key]: event.target.value }))} />;
  const select = (key: string, label: string, choices: { value: string; label: string }[], disabled = false) => <TextField select label={label} value={values[key]} disabled={busy || disabled} onChange={(event) => setValues((old) => ({ ...old, [key]: event.target.value, ...(key === 'entityId' ? { attribute: snapshot.entities.find((x) => x.id === event.target.value)?.kind === 'item' ? 'holder' : '', valueEntityId: '' } : {}), ...(['plotStatus', 'kind'].includes(key) ? { parentId: '' } : {}) }))}>{choices.map((item) => <MenuItem key={item.value} value={item.value}>{item.label}</MenuItem>)}</TextField>;
  const stateMode = editor.kind === 'state' || editor.kind === 'candidate';
  const entity = snapshot.entities.find((item) => item.id === values.entityId);
  const title = editor.kind === 'decision' ? actionLabels[editor.action!] : editor.kind === 'resolve' ? '重新核对来源' : editor.kind === 'extract' ? '从原文提取候选' : editor.kind === 'entity' ? '新增人物或物品' : editor.kind === 'outline' ? editor.outline ? '编辑大纲' : '新增大纲' : editor.kind === 'candidate' ? '提交状态候选' : editor.state ? '修正状态记录' : '记录作者确认状态';
  const submit = async () => {
    setValidation('');
    const key = JSON.stringify({ values, withSource, source, revisionId, version: snapshot.version });
    if (attempt.current?.key !== key) attempt.current = { key, id: crypto.randomUUID() };
    const requestId = attempt.current.id;
    const send = (operation: MemoryOperation) => onSave(operation, requestId);
    try {
      if (editor.kind === 'entity') {
        if (!values.name.trim()) throw new Error('请填写实体名称');
        await send((cmd, signal) => storyMemoryApi.createEntity(novelId, { ...cmd, name: values.name.trim(), description: values.description.trim(), kind: values.entityKind as StoryEntity['kind'] }, signal));
      } else if (editor.kind === 'decision') {
        await send((cmd, signal) => storyMemoryApi.decide(novelId, editor.candidate!.id, { ...cmd, action: editor.action!, reason: values.reason.trim() }, signal));
      } else if (editor.kind === 'extract') {
        if (!revisionId) throw new Error('请先选择可读取的来源原文');
        await send((cmd, signal) => storyMemoryApi.extract(novelId, { ...cmd, source_revision_id: revisionId }, signal));
      } else {
        if (withSource && !source) throw new Error('请填写可核对的来源原句');
        const sourceRefs = withSource && source ? [source] : [];
        if (editor.kind === 'resolve') {
          if (!values.reason.trim()) throw new Error('请说明重新核对的理由');
          await send((cmd, signal) => storyMemoryApi.resolve(novelId, editor.outline ? 'outline' : 'states', editor.outline?.id ?? editor.state!.id, { ...cmd, source_refs: sourceRefs, reason: values.reason.trim() }, signal));
        } else if (editor.kind === 'outline') {
          if (!values.title.trim()) throw new Error('请填写大纲标题');
          if (values.kind !== 'volume' && !values.chapter.trim()) throw new Error('章和场景必须填写对应章节');
          const data = { parent_id: values.parentId || null, kind: values.kind as OutlineNode['kind'], plot_status: values.plotStatus as OutlineNode['plot_status'], chapter_number: values.chapter.trim() ? positive(values.chapter) : null, title: values.title.trim(), conflict: values.conflict, outcome: values.outcome, source_refs: withSource ? sourceRefs : (editor.outline?.source_refs ?? []).map(({ revision_id, quote, start }) => ({ revision_id, quote, start })) };
          await send((cmd, signal) => storyMemoryApi.saveOutline(novelId, editor.outline?.id ?? null, { ...cmd, ...data }, signal));
        } else if (stateMode) {
          if (!entity || !values.attribute.trim() || !values.value.trim()) throw new Error('请选择实体并填写属性与状态');
          if (entity.kind === 'item' && values.attribute === 'quantity' && !/^\d+$/.test(values.value.trim())) throw new Error('物品数量必须为非负整数');
          const data = { entity_id: entity.id, attribute: values.attribute.trim(), value: values.value.trim(), value_entity_id: values.attribute === 'quantity' ? null : values.valueEntityId || null, effective_chapter: positive(values.effectiveChapter), source_refs: sourceRefs };
          if (editor.kind === 'candidate') await send((cmd, signal) => storyMemoryApi.createCandidate(novelId, { ...cmd, ...data }, signal));
          else if (editor.state) await send((cmd, signal) => storyMemoryApi.replaceState(novelId, editor.state!.id, { ...cmd, ...data }, signal));
          else await send((cmd, signal) => storyMemoryApi.createState(novelId, { ...cmd, ...data }, signal));
        }
      }
    } catch (failure) { setValidation(failure instanceof Error ? failure.message : '操作失败，填写内容已保留'); }
  };
  return <Dialog open fullWidth maxWidth="sm" onClose={() => { if (!busy) onClose(); }}>
    <DialogTitle>{title}</DialogTitle>
    <DialogContent><Stack spacing={2} sx={{ pt: 1 }}>
      {(validation || error) && <Alert severity="error">{validation || error}</Alert>}
      {editor.kind === 'entity' && <>{field('name', '实体名称', false, 100)}{field('description', '实体说明（区分同名，可留空）', true, 500)}{select('entityKind', '实体类型', Object.entries(entityLabels).map(([value, label]) => ({ value, label })))}<Typography variant="caption">同名人物可分别建立，通过说明区分，例如“女医师”和“木匠”；每个实体独立记录状态。</Typography></>}
      {editor.kind === 'outline' && <>
        {field('title', '大纲标题', false, 200)}
        {select('kind', '大纲层级', [{ value: 'volume', label: '卷' }, { value: 'chapter', label: '章' }, { value: 'scene', label: '场景' }])}
        {select('parentId', '上级大纲', [{ value: '', label: '无上级' }, ...snapshot.outline_nodes.filter((x) => x.id !== editor.outline?.id && x.plot_status === values.plotStatus && values.kind !== 'volume' && (values.kind === 'chapter' ? x.kind === 'volume' : x.kind === 'chapter' && x.chapter_number === Number(values.chapter))).map((x) => ({ value: x.id, label: x.title }))])}
        {select('plotStatus', '计划与实际', [{ value: 'planned', label: '计划中' }, { value: 'occurred', label: '已发生' }])}
        {field('chapter', '对应章节（卷可留空）', false, 9)}{field('conflict', '冲突与目标', true)}{field('outcome', '结果或预期结果', true)}
        <Typography variant="caption">计划中的内容不会作为已经发生的剧情召回。</Typography>
      </>}
      {stateMode && <>
        {select('entityId', '状态归属实体', snapshot.entities.map((x, index) => ({ value: x.id, label: `${storyEntityLabel(x)} · ${entityLabels[x.kind]} · ${index + 1}` })), Boolean(editor.state))}
        {entity?.kind === 'item' ? select('attribute', '物品属性', [{ value: 'holder', label: '当前持有者' }, { value: 'owner', label: '所有者' }, { value: 'quantity', label: '数量' }], Boolean(editor.state)) : field('attribute', '属性（如位置、身份）', false, 100)}
        {field('value', '状态内容', true)}
        {values.attribute !== 'quantity' && select('valueEntityId', '关联实体（持有者或所有者）', [{ value: '', label: '无关联 / 未知' }, ...snapshot.entities.filter((x) => x.kind !== 'item').map((x, index) => ({ value: x.id, label: `${storyEntityLabel(x)} · ${entityLabels[x.kind]} · ${index + 1}` }))])}
        {field('effectiveChapter', '生效章节', false, 9)}
        <Typography variant="caption">{editor.kind === 'candidate' ? '提交后等待作者审阅，不直接改变正式状态。' : '保存表示作者已确认；旧状态区间保留用于回查。'}</Typography>
      </>}
      {editor.kind === 'decision' && <>
        <Typography>{storyEntityLabel(snapshot.entities.find((x) => x.id === editor.candidate?.entity_id))} · {editor.candidate?.attribute}：{editor.candidate?.value}</Typography>
        <Typography variant="body2">{editor.action === 'confirm' ? '确认后将从候选指定章节生效。请先核对原文与持有、所有权等含义。' : editor.action === 'revoke' ? '撤销后这项候选不再作为正式状态，历史仍保留。' : '拒绝后候选保留审阅记录，不进入正式状态。'}</Typography>
        {editor.candidate?.source_refs.map((ref, index) => <Typography key={index} variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>引用：{ref.quote}</Typography>)}
        {field('reason', '审阅理由（可留空）', true, 1000)}
      </>}
      {editor.kind === 'resolve' && <>
        <Alert severity="warning">原文已变化。请重新核对；不关联新出处时，表示你将此项独立确认为手写设定。</Alert>
        {field('reason', '重新核对理由', true, 1000)}
      </>}
      {editor.kind === 'extract' && <Typography variant="body2">使用所选已保存原文调用 AI；单章最多 20000 字符，最多处理 40 个已有实体。提取的状态仍须审阅确认，不会自动覆盖作者设定。</Typography>}
      {['outline', 'state', 'resolve'].includes(editor.kind) && <FormControlLabel control={<Checkbox checked={withSource} disabled={busy} onChange={(_event, checked) => setWithSource(checked)} />} label={editor.kind === 'resolve' ? '关联重新核对的原文' : '关联原文出处'} />}
      {withSource && <MemorySourcePicker novelId={novelId} chapterId={chapterId} disabled={busy} quoteRequired={editor.kind !== 'extract'} onChange={sourceChanged} />}
    </Stack></DialogContent>
    <DialogActions><Button disabled={busy} onClick={onClose}>取消</Button><Button variant="contained" disabled={busy || (editor.kind === 'decision' && editor.action === 'confirm' && editor.candidate?.source_status !== 'ready')} onClick={() => void submit()}>{busy ? '处理中…' : title}</Button></DialogActions>
  </Dialog>;
}
