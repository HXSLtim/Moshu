'use client';

import { useState } from 'react';
import { Alert, Box, Button, Chip, Divider, Stack, Typography } from '@mui/material';
import { api } from '@/lib/api';
import { storyMemoryApi } from '@/lib/storyMemory';
import type { AgentAction } from '@/types/writingChat';

interface Props {
  novelId: number;
  novelLifecycleId?: string | null;
  actions: AgentAction[];
  uncertainties: string[];
  onApplied: () => void;
}

const describe = (action: AgentAction): string => {
  if (action.kind === 'project_info') {
    const parts: string[] = [];
    if (action.genre) parts.push(`类型 → ${action.genre}`);
    if (action.description) parts.push(`简介 → ${action.description}`);
    if (action.worldview) parts.push(`世界观 → ${action.worldview}`);
    return parts.join('；');
  }
  if (action.kind === 'entity') return `${action.name}（${action.description}）`;
  if (action.kind === 'fact') return `${action.subject} 的 ${action.attribute}：${action.value}`;
  return `${action.node_kind === 'volume' ? '卷' : '章'}「${action.title}」：${action.summary}`;
};

/** Agent 自己提出的设定写入动作；作者确认后才落库。 */
export default function AgentActionsCard({ novelId, novelLifecycleId, actions, uncertainties, onApplied }: Props) {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [error, setError] = useState('');

  if (done) return <Alert severity="success" sx={{ mt: 1 }}>已写入设定。可以在左侧「项目与设定」里查看和修改。</Alert>;
  if (dismissed || actions.length === 0) return null;

  const apply = async () => {
    if (!novelLifecycleId) { setError('项目身份尚未就绪，请刷新后重试'); return; }
    setBusy(true); setError('');
    try {
      const project = actions.find((action) => action.kind === 'project_info');
      if (project && project.kind === 'project_info') {
        await api.updateNovel(novelId, {
          ...(project.genre ? { genre: project.genre } : {}),
          ...(project.description ? { description: project.description } : {}),
          ...(project.worldview ? { worldview: project.worldview } : {}),
        });
      }
      const entities = actions.filter((action) => action.kind === 'entity');
      if (entities.length > 0) {
        let memory = await storyMemoryApi.get(novelId);
        for (const entity of entities) {
          if (entity.kind !== 'entity') continue;
          memory = await storyMemoryApi.createEntity(novelId, {
            request_id: crypto.randomUUID(), expected_version: memory.version,
            novel_lifecycle_id: novelLifecycleId, name: entity.name,
            kind: entity.entity_kind, description: entity.description,
          });
        }
      }
      const outlines = actions.filter((action) => action.kind === 'outline');
      if (outlines.length > 0) {
        let memory = await storyMemoryApi.get(novelId);
        for (const node of outlines) {
          if (node.kind !== 'outline') continue;
          memory = await storyMemoryApi.saveOutline(novelId, null, {
            request_id: crypto.randomUUID(), expected_version: memory.version,
            novel_lifecycle_id: novelLifecycleId, parent_id: null, kind: node.node_kind,
            plot_status: 'planned', chapter_number: node.chapter_number,
            title: node.title, conflict: '', outcome: node.summary, source_refs: [],
          });
        }
      }
      for (const fact of actions) {
        if (fact.kind !== 'fact') continue;
        await api.createStoryFact({
          novel_id: novelId, subject: fact.subject, attribute: fact.attribute, value: fact.value,
        });
      }
      setDone(true);
      onApplied();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '写入失败，请重试');
    } finally { setBusy(false); }
  };

  const grouped = {
    project_info: actions.filter((action) => action.kind === 'project_info'),
    entity: actions.filter((action) => action.kind === 'entity'),
    fact: actions.filter((action) => action.kind === 'fact'),
    outline: actions.filter((action) => action.kind === 'outline'),
  };
  const sectionLabel = { project_info: '项目信息', entity: '实体', fact: '设定事实', outline: '大纲' } as const;

  return (
    <Box sx={{ mt: 1.5, p: 2, border: 1, borderColor: 'primary.main', borderRadius: 2 }}>
      <Typography variant="subtitle2" fontWeight={700} gutterBottom>AI 从这段交流里整理出的设定</Typography>
      <Stack spacing={1.5}>
        {(['project_info', 'entity', 'fact', 'outline'] as const).map((kind) => grouped[kind].length > 0 && (
          <Box key={kind}>
            <Typography variant="body2" fontWeight={700}>{sectionLabel[kind]}</Typography>
            {grouped[kind].map((action, index) => <Typography key={index} variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>· {describe(action)}</Typography>)}
          </Box>
        ))}
      </Stack>
      {uncertainties.length > 0 && <Alert severity="warning" sx={{ mt: 1.5 }}>
        <Typography variant="body2" fontWeight={700}>还不能确定</Typography>
        {uncertainties.map((item) => <Typography key={item} variant="body2">· {item}</Typography>)}
      </Alert>}
      {error && <Alert severity="error" sx={{ mt: 1.5 }}>{error}</Alert>}
      <Divider sx={{ my: 1.5 }} />
      <Stack direction="row" gap={1}>
        <Button size="small" variant="contained" disabled={busy} onClick={() => void apply()}>
          {busy ? '正在写入…' : '确认写入设定'}
        </Button>
        <Button size="small" disabled={busy} onClick={() => setDismissed(true)}>先不写入</Button>
      </Stack>
    </Box>
  );
}

export { describe as describeAgentAction };

/** Chip 形式的摘要，供列表或提示使用。 */
export function AgentActionChips({ actions }: { actions: AgentAction[] }) {
  return <Stack direction="row" gap={0.5} flexWrap="wrap">{actions.map((action, index) => <Chip key={index} size="small" variant="outlined" label={describe(action)} />)}</Stack>;
}
