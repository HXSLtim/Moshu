'use client';

import { useState } from 'react';
import { Alert, Box, Button, Chip, Divider, Stack, Typography } from '@mui/material';
import { api } from '@/lib/api';
import type { AgentAction, WritingTurn } from '@/types/writingChat';

interface Props {
  novelId: number;
  /** 所属对话轮的服务端 id；本地乐观轮为 0，尚不能发起决策。 */
  turnId: number;
  actions: AgentAction[];
  uncertainties: string[];
  /** 决策成功后回传整轮，actions 已带服务端写回的 decision/decided_at。 */
  onDecided: (turn: WritingTurn) => void;
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

/** Agent 自己提出的设定写入动作；终态以服务端写回的 decision 为准，刷新后不再复活。 */
export default function AgentActionsCard({ novelId, turnId, actions, uncertainties, onDecided }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  if (actions.length === 0) return null;
  const allDecided = actions.every((action) => action.decision);

  const decide = async (decision: 'applied' | 'skipped') => {
    if (turnId <= 0) return;
    setBusy(true); setError('');
    try {
      // 只提交尚未决策的条目；已 applied 的条目不可改口，交由服务端裁决兜底。
      const indexes = actions.map((action, index) => (action.decision ? null : index)).filter((index): index is number => index !== null);
      if (indexes.length === 0) return;
      const updated = await api.decideTurnActions(novelId, turnId, decision);
      onDecided(updated);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '操作失败，请重试');
    } finally { setBusy(false); }
  };

  if (allDecided) {
    const appliedCount = actions.filter((action) => action.decision === 'applied').length;
    const skippedCount = actions.length - appliedCount;
    if (skippedCount === 0) return <Alert severity="success" sx={{ mt: 1.5 }}>已写入设定。可以在左侧「项目与设定」里查看和修改。</Alert>;
    if (appliedCount === 0) return <Alert severity="info" sx={{ mt: 1.5 }}>这些设定已按你的选择跳过，没有写入。之后想补写，可以在左侧「项目与设定」里手动添加。</Alert>;
    // 混合终态（正常界面流程不会产生，仅服务端按条决策时可能出现）：逐条展示状态，不再提供按钮。
    return <Box sx={{ mt: 1.5 }}>
      {actions.map((action, index) => <Typography key={index} variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>· {describe(action)}<Chip size="small" label={action.decision === 'applied' ? '已写入' : '已跳过'} color={action.decision === 'applied' ? 'success' : 'default'} variant="outlined" sx={{ ml: 1, height: 18, '& .MuiChip-label': { fontSize: 10, px: 0.5 } }} /></Typography>)}
      <Alert severity="info" sx={{ mt: 1 }}>已处理：写入 {appliedCount} 项，跳过 {skippedCount} 项。</Alert>
    </Box>;
  }

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
            {grouped[kind].map((action, index) => <Typography key={index} variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>· {describe(action)}{action.decision && <Chip size="small" label={action.decision === 'applied' ? '已写入' : '已跳过'} color={action.decision === 'applied' ? 'success' : 'default'} variant="outlined" sx={{ ml: 1, height: 18, '& .MuiChip-label': { fontSize: 10, px: 0.5 } }} />}</Typography>)}
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
        <Button size="small" variant="contained" disabled={busy || turnId <= 0} onClick={() => void decide('applied')}>
          {busy ? '正在写入…' : '确认写入设定'}
        </Button>
        <Button size="small" disabled={busy || turnId <= 0} onClick={() => void decide('skipped')}>先不写入</Button>
        {turnId <= 0 && <Typography variant="caption" color="text.secondary" sx={{ alignSelf: 'center' }}>对话保存后才能确认</Typography>}
      </Stack>
    </Box>
  );
}

export { describe as describeAgentAction };

/** Chip 形式的摘要，供列表或提示使用。 */
export function AgentActionChips({ actions }: { actions: AgentAction[] }) {
  return <Stack direction="row" gap={0.5} flexWrap="wrap">{actions.map((action, index) => <Chip key={index} size="small" variant="outlined" label={describe(action)} />)}</Stack>;
}
