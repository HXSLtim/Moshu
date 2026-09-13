'use client';

import { useEffect, useRef, useState } from 'react';
import { writingProposalApi } from '@/lib/writingProposal';
import { contentHash } from '@/lib/writingChat';
import type { Chapter } from '@/types';

export interface WritingScope {
  novelId: number;
  novelLifecycleId?: string;
  chapterId: number | null;
  chapterLifecycleId?: string;
  chapterVersion?: number;
  currentContent: string;
  canApply?: boolean;
  onProposalAccepted?: (chapter: Chapter) => void;
}
/** 所有正文候选经服务器命令采纳；网络重试复用命令身份，在途新稿始终保留。 */
export function useWritingProposal(props: WritingScope) {
  const [deciding, setDeciding] = useState<string | null>(null);
  const [decisions, setDecisions] = useState<Record<string, string>>({});
  const [error, setError] = useState('');
  const current = useRef(props); current.current = props;
  const active = useRef(true);
  const controllerRef = useRef<AbortController | null>(null);
  const requestIds = useRef(new Map<string, string>());
  useEffect(() => { active.current = true; return () => { active.current = false; controllerRef.current?.abort(); }; }, []);
  const decide = async (proposalId: string, decision: 'accept' | 'reject', candidateContent?: string) => {
    if (controllerRef.current) return;
    const snapshot = current.current;
    const controller = new AbortController(); controllerRef.current = controller;
    const sameScope = () => active.current && !controller.signal.aborted && current.current.novelId === snapshot.novelId && current.current.novelLifecycleId === snapshot.novelLifecycleId;
    const sameDraft = () => sameScope() && current.current.chapterId === snapshot.chapterId && current.current.chapterLifecycleId === snapshot.chapterLifecycleId && current.current.chapterVersion === snapshot.chapterVersion && current.current.currentContent === snapshot.currentContent && current.current.canApply;
    setDeciding(proposalId); setError('');
    try {
      if (decision === 'accept' && !snapshot.canApply) throw new Error('请先保存正文并完成身份核验，再采纳候选');
      const proposal = await writingProposalApi.get(snapshot.novelId, proposalId, controller.signal);
      if (!sameScope()) return;
      if (proposal.novel_lifecycle_id !== snapshot.novelLifecycleId || proposal.novel_id !== snapshot.novelId) throw new Error('候选作品来源已变化，请重新打开作品');
      if (proposal.status !== 'pending') { setDecisions((old) => ({ ...old, [proposalId]: proposal.status })); return; }
      if (decision === 'accept' && (proposal.chapter_id !== snapshot.chapterId || proposal.chapter_lifecycle_id !== snapshot.chapterLifecycleId || proposal.base_version !== snapshot.chapterVersion || await contentHash(snapshot.currentContent) !== proposal.base_content_hash || !sameDraft())) {
        throw new Error('正文、版本或来源已变化，请先保存并重新生成候选');
      }
      const key = JSON.stringify([proposalId, decision, candidateContent]);
      const requestId = requestIds.current.get(key) ?? crypto.randomUUID(); requestIds.current.set(key, requestId);
      const result = decision === 'accept'
        ? await writingProposalApi.accept(snapshot.novelId, proposalId, { request_id: requestId, expected_version: proposal.base_version, expected_content_hash: proposal.base_content_hash, ...(candidateContent === undefined ? {} : { candidate_content: candidateContent }) }, controller.signal)
        : await writingProposalApi.reject(snapshot.novelId, proposalId, requestId, controller.signal);
      if (!sameScope()) return;
      setDecisions((old) => ({ ...old, [proposalId]: result.proposal.status }));
      if (result.chapter) {
        if (sameDraft()) snapshot.onProposalAccepted?.(result.chapter);
        else setError('候选已保存到服务器；编辑器中有后续修改，已保留，请核对版本后继续。');
      }
    } catch (failure) { if (sameScope()) setError(failure instanceof Error ? failure.message : '候选确认失败，内容仍保留'); }
    finally { if (controllerRef.current === controller) controllerRef.current = null; if (sameScope()) setDeciding(null); }
  };
  return { deciding, decisions, error, decide, clearError: () => setError('') };
}
