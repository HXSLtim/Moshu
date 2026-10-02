'use client';

import { useEffect, useState } from 'react';
import { Alert, Button, Stack, Typography } from '@mui/material';
import { writingProposalApi } from '@/lib/writingProposal';
import { useWritingProposal, type WritingScope } from '@/hooks/useWritingProposal';

interface Props extends WritingScope { proposalId: string; candidateContent?: string; acceptLabel?: string; /** 稿件落点说明（来自轮次 result.landing），确认前让作者看清写到哪里。 */ landing?: string }
export default function WritingProposalActions(props: Props) {
  const { proposalId } = props;
  const [status, setStatus] = useState('');
  const [loadError, setLoadError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const decision = useWritingProposal(props);
  useEffect(() => {
    const controller = new AbortController(); setStatus(''); setLoadError('');
    void writingProposalApi.get(props.novelId, proposalId, controller.signal).then((proposal) => { if (!controller.signal.aborted) setStatus(proposal.status); })
      .catch((failure) => { if (!controller.signal.aborted) setLoadError(failure instanceof Error ? failure.message : '读取候选状态失败'); });
    return () => controller.abort();
  }, [props.novelId, props.novelLifecycleId, proposalId, attempt]);
  const actualStatus = decision.decisions[proposalId] ?? status;
  return <Stack spacing={1}>
    {(decision.error || loadError) && <Alert severity="warning" action={loadError ? <Button onClick={() => setAttempt((value) => value + 1)}>重试读取</Button> : undefined}>{decision.error || loadError}</Alert>}
    {['accepted', 'rejected', 'cancelled'].includes(actualStatus) ? <Typography variant="caption">{actualStatus === 'accepted' ? '已采纳' : actualStatus === 'rejected' ? '已拒绝' : '候选已取消'}</Typography> : <Stack spacing={0.5}>
      {props.landing && <Typography variant="caption" color="text.secondary">将写入：{props.landing}</Typography>}
      <Stack direction="row" gap={1}>
        <Button variant="contained" size="small" disabled={actualStatus !== 'pending' || !props.canApply || Boolean(decision.deciding) || props.candidateContent?.trim() === ''} onClick={() => void decision.decide(proposalId, 'accept', props.candidateContent)}>{props.acceptLabel ?? '采纳到本章'}</Button>
        <Button size="small" disabled={actualStatus !== 'pending' || Boolean(decision.deciding)} onClick={() => void decision.decide(proposalId, 'reject')}>拒绝候选</Button>
      </Stack>
    </Stack>}
  </Stack>;
}
