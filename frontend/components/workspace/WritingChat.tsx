'use client';

import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { Alert, Box, Button, CircularProgress, IconButton, ListItemIcon, ListItemText, Menu, MenuItem, TextField, Tooltip, Typography } from '@mui/material';
import SendIcon from '@mui/icons-material/Send';
import StopIcon from '@mui/icons-material/Stop';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import AddIcon from '@mui/icons-material/Add';
import ActionCard, { ACTION_KINDS, type ActionCardState, type ActionKind } from './ActionCard';
import AiWritingAssistant from './AiWritingAssistant';
import TextRewriter from './TextRewriter';
import OrchestrationPanel from './OrchestrationPanel';
import ConsistencyChecker from './ConsistencyChecker';
import PlotOptionsGenerator from './PlotOptionsGenerator';
import ResearchAssistant from './ResearchAssistant';
import { api } from '@/lib/api';
import { mergeWritingTurns } from '@/lib/writingChat';
import type { AgentAction, AgentTurnResult, WritingMode, WritingTurn } from '@/types/writingChat';
import ContextSources from './ContextSources';
import ExecutionUsageLine from './ExecutionUsageLine';
import WritingProposalActions from './WritingProposalActions';
import AgentActionsCard from './AgentActionsCard';
import type { Chapter, Novel } from '@/types';

export type PlotOptionHint = { id: number; title: string; summary: string; impact?: string | null; risk?: string | null };

interface Props {
  novelId: number;
  chapterId: number | null;
  chapterTitle: string;
  currentContent: string;
  onContentGenerated: (content: string) => void;
  chapterVersion?: number;
  novelLifecycleId?: string;
  chapterLifecycleId?: string;
  canApply?: boolean;
  onProposalAccepted?: (chapter: Chapter) => void;
  /** 设定交流写入后通知外层刷新项目信息。 */
  onSettingsApplied?: () => void;
  /** 动作卡片透传:一致性自查与改写/剧情面板所需的工作区状态。 */
  novel?: Novel | null;
  currentChapter?: Chapter | null;
  selectedText?: string | null;
  selectionStart?: number | null;
  selectionEnd?: number | null;
  plotDirectionHint?: string | null;
  onPlotSelected?: (option: PlotOptionHint) => void;
  onPlotSelectedAndContinue?: (option: PlotOptionHint) => void;
  onError?: (message: string) => void;
}
export interface WritingChatRef { triggerContinue: (instruction?: string) => void }

const modeLabels: Record<WritingMode, string> = { discuss: '讨论剧情', continue: '续写正文', advanced_continue: '高级续写', rewrite: '改写本章', outline: '规划大纲', character: '设计角色', check: '检查本章', new_chapter: '起草下一章' };
const manuscriptModes = new Set<WritingMode>(['continue', 'advanced_continue', 'rewrite', 'new_chapter']);
const readToolLabels: Record<string, string> = {
  search_story_bible: '查阅了设定账本',
  lookup_character: '查阅了角色卡',
  read_chapter_digest: '查阅了前章简介',
  get_outline: '查阅了全书大纲',
  search_manuscript: '检索了前文正文',
  check_manuscript: '自查了稿件一致性',
};

const WritingChatSession = forwardRef<WritingChatRef, Props>(function WritingChatSession(props, ref) {
  const { novelId, chapterId, chapterTitle, currentContent } = props;
  const [turns, setTurns] = useState<WritingTurn[]>([]);
  const [draft, setDraft] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [toolTrail, setToolTrail] = useState<string[]>([]);
  const [attempt, setAttempt] = useState(0);
  const [actions, setActions] = useState<ActionCardState[]>([]);
  const [menuAnchor, setMenuAnchor] = useState<HTMLElement | null>(null);
  const openAction = (kind: ActionKind) => {
    setMenuAnchor(null);
    followBottom.current = true;
    setActions((previous) => [...previous, { id: crypto.randomUUID(), kind, created_at: new Date().toISOString() }]);
  };
  const closeAction = (id: string) => setActions((previous) => previous.filter((action) => action.id !== id));
  const mounted = useRef(true);
  const sendingRef = useRef(false);
  const latest = useRef(props);
  latest.current = props;
  const controllerRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const followBottom = useRef(true);
  const pending = turns.findLast((turn) => turn.status === 'pending');
  const pendingId = pending?.request_id;
  const latestSavedId = turns.reduce((value, turn) => Math.max(value, turn.id), 0);

  const merge = useCallback((incoming: WritingTurn[]) => setTurns((previous) => mergeWritingTurns(previous, incoming)), []);
  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    setLoading(true);
    void api.listWritingTurns(novelId, undefined, { signal: controller.signal }).then((items) => {
      if (controller.signal.aborted) return;
      merge(items); setHasMore(items.filter((turn) => turn.id > 0).length >= 30); setError('');
    }).catch((failure) => {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : '读取对话失败');
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { mounted.current = false; controller.abort(); controllerRef.current?.abort(); };
  }, [novelId, attempt, merge]);

  useEffect(() => {
    if (!pendingId) return;
    const controller = new AbortController();
    const timer = setInterval(() => {
      void api.listWritingTurns(novelId, undefined, { signal: controller.signal }).then((items) => {
        if (!controller.signal.aborted) merge(items);
      }).catch(() => {});
    }, 2000);
    return () => { clearInterval(timer); controller.abort(); };
  }, [pendingId, novelId, merge]);

  const last = turns[turns.length - 1];
  useEffect(() => {
    const container = scrollRef.current;
    if (container && followBottom.current) container.scrollTop = container.scrollHeight;
  }, [last?.request_id, last?.assistant_text, last?.status, loading]);

  const send = useCallback(async (override?: string, nextMode?: WritingMode) => {
    if (!chapterId || sendingRef.current || pending || loading) return;
    // 默认就是 Agent 入口：作者只说话，由模型判断该回答、改设定还是起草正文。
    const selectedMode: WritingMode = nextMode ?? 'discuss';
    const text = (override ?? draft).trim() || (selectedMode === 'continue' ? '请沿着当前正文继续写约 500 字。' : '');
    if (!text) return;
    if (manuscriptModes.has(selectedMode) && !latest.current.canApply) {
      setError('请先保存正文并完成身份核验，再生成可采纳候选'); return;
    }
    const requestId = crypto.randomUUID();
    const payload = { request_id: requestId, chapter_id: chapterId, mode: selectedMode, message: text, current_content: currentContent,
      expected_version: manuscriptModes.has(selectedMode) ? latest.current.chapterVersion : undefined,
      expected_novel_lifecycle_id: latest.current.novelLifecycleId,
      expected_chapter_lifecycle_id: latest.current.chapterLifecycleId };
    const controller = new AbortController();
    controllerRef.current = controller;
    sendingRef.current = true;
    setSending(true); setError(''); setDraft(''); setToolTrail([]); followBottom.current = true;
    merge([{ id: 0, local_order: latestSavedId + 0.5, request_id: requestId, novel_id: novelId, chapter_id: chapterId, chapter_title: chapterTitle,
      mode: payload.mode, user_text: text, assistant_text: '', base_content_hash: '', status: 'pending', error: null, created_at: new Date().toISOString() }]);
    const patchLocal = (patch: Partial<WritingTurn>) => {
      if (!mounted.current) return;
      setTurns((previous) => previous.map((turn) => turn.request_id === requestId ? { ...turn, ...patch } : turn));
    };
    const toolActions: AgentAction[] = [];
    try {
      await api.streamWritingTurn(novelId, payload, {
        onTurn: (incoming) => patchLocal(incoming),
        onChunk: (content) => {
          if (!mounted.current || !content) return;
          setTurns((previous) => previous.map((turn) => turn.request_id === requestId
            ? { ...turn, assistant_text: turn.assistant_text + content } : turn));
        },
        onTool: (name, data) => {
          if (!mounted.current) return;
          if (data && typeof data === 'object' && 'kind' in data) {
            toolActions.push(data as unknown as AgentAction);
            patchLocal({ result: { reply: '', actions: [...toolActions], uncertainties: [] } as never });
            return;
          }
          // 只读检索与自查事件只展示轨迹，不产生待确认动作。
          const label = readToolLabels[name];
          if (label) setToolTrail((previous) => [...previous, label]);
        },
        onDone: (turn) => { merge([turn]); },
      }, { signal: controller.signal });
    } catch (failure) {
      if (!mounted.current || (failure instanceof Error && failure.name === 'AbortError')) return;
      // 网络响应丢失时先核对服务端记录，避免把已完成回复误报成失败。
      try {
        const stored = await api.listWritingTurns(novelId);
        if (!mounted.current) return;
        merge(stored);
        if (!stored.some((turn) => turn.request_id === requestId)) {
          setTurns((previous) => previous.map((turn) => turn.request_id === requestId ? { ...turn, status: 'failed', error: '消息未保存到服务器，请重新发送。' } : turn));
          setDraft((previous) => previous || text);
        }
      } catch {
        if (mounted.current) setTurns((previous) => previous.map((turn) => turn.request_id === requestId && turn.id === 0 ? { ...turn, status: 'failed', error: '暂时无法确认消息是否保存，请恢复连接后刷新对话。' } : turn));
        if (mounted.current) setDraft((previous) => previous || text);
      }
      if (mounted.current) setError(failure instanceof Error ? failure.message : '连接中断，请刷新对话确认结果');
    } finally {
      if (controllerRef.current === controller) {
        sendingRef.current = false;
        if (mounted.current) setSending(false);
      }
    }
  }, [chapterId, chapterTitle, currentContent, draft, loading, merge, novelId, pending, latestSavedId]);

  useImperativeHandle(ref, () => ({ triggerContinue: (instruction) => { void send(instruction, 'continue'); } }), [send]);

  const loadMore = async () => {
    const first = turns.find((turn) => turn.id > 0);
    if (!first) return;
    setLoadingMore(true);
    try {
      const items = await api.listWritingTurns(novelId, first.id);
      if (mounted.current) { merge(items); setHasMore(items.length === 30); }
    } catch { if (mounted.current) setError('读取更早对话失败，请重试'); }
    finally { if (mounted.current) setLoadingMore(false); }
  };

  const renderTurn = (turn: WritingTurn) => <Box sx={{ mb: 3 }}>

        <Box sx={{ p: 1.5, bgcolor: 'action.hover', borderRadius: 1, mb: 2 }}>
          <Typography variant="caption" color="text.secondary">你 · {turn.chapter_title} · {modeLabels[turn.mode]}</Typography>
          <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', mt: 0.5 }}>{turn.user_text}</Typography>
        </Box>
        <Typography variant="caption" color="primary">Nai</Typography>
        {turn.status === 'pending' ? <Box role="status" sx={{ display: 'flex', gap: 1, alignItems: 'center', py: 1, flexWrap: 'wrap' }}><CircularProgress size={12} /><Typography variant="body2">{turn.job_status === 'queued' ? '创作任务已保存，等待执行…' : '正在思考与创作…'}</Typography>{toolTrail.length > 0 && <Typography variant="caption" color="text.secondary">{toolTrail[toolTrail.length - 1]}（本轮已执行 {toolTrail.length} 步查阅）</Typography>}</Box>
          : turn.status !== 'completed' ? <Alert severity="info">{turn.error || '本轮未完成'}<Button size="small" onClick={() => setDraft(turn.user_text)}>重新编辑</Button></Alert>
          : <>
            <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', lineHeight: 1.9, mt: 0.5 }}>{turn.assistant_text}</Typography>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 1 }}>
              <Tooltip title="复制回复"><IconButton size="small" aria-label="复制回复" onClick={() => { void navigator.clipboard.writeText(turn.assistant_text).catch(() => setError('复制失败，请手动选择回复复制')); }}><ContentCopyIcon fontSize="small" /></IconButton></Tooltip>
              {turn.proposal_id ? <WritingProposalActions key={turn.proposal_id} {...props} canApply={props.canApply && turn.chapter_id === chapterId} proposalId={turn.proposal_id} acceptLabel={turn.mode === 'new_chapter' ? '确认创建新章' : '采纳到本章'} /> : manuscriptModes.has(turn.mode) && <Button size="small" disabled>采纳到本章</Button>}
              {turn.chapter_id !== chapterId && <Typography variant="caption" color="text.secondary">来自其他章节</Typography>}
            </Box>
            {turn.result && Array.isArray((turn.result as unknown as AgentTurnResult).actions)
              && ((turn.result as unknown as AgentTurnResult).actions.length > 0) && <AgentActionsCard
                novelId={novelId}
                novelLifecycleId={props.novelLifecycleId}
                actions={(turn.result as unknown as AgentTurnResult).actions}
                uncertainties={(turn.result as unknown as AgentTurnResult).uncertainties ?? []}
                onApplied={() => { setAttempt((value) => value + 1); props.onSettingsApplied?.(); }}
              />}
          </>}
        <ContextSources novelId={novelId} manifest={turn.context_manifest} />
        <ExecutionUsageLine execution={turn.execution} />

  </Box>;

  const renderAction = (action: ActionCardState) => {
    switch (action.kind) {
      case 'orchestrate':
        return <OrchestrationPanel novelId={novelId} chapterId={chapterId} novelLifecycleId={props.novelLifecycleId}
          chapterLifecycleId={props.chapterLifecycleId} chapterVersion={props.chapterVersion}
          currentContent={currentContent} canApply={props.canApply} onProposalAccepted={props.onProposalAccepted} />;
      case 'continue':
        return <AiWritingAssistant novelId={novelId} chapterId={chapterId} currentContent={currentContent}
          onError={props.onError ?? (() => {})} plotDirectionHint={props.plotDirectionHint} chapterVersion={props.chapterVersion}
          novelLifecycleId={props.novelLifecycleId} chapterLifecycleId={props.chapterLifecycleId}
          canApply={props.canApply} onProposalAccepted={props.onProposalAccepted} />;
      case 'rewrite':
        return <TextRewriter novelId={novelId} chapterId={chapterId} currentContent={currentContent}
          selectedText={props.selectedText ?? ''} selectionStart={props.selectionStart ?? null} selectionEnd={props.selectionEnd ?? null}
          onError={props.onError ?? (() => {})} chapterVersion={props.chapterVersion} novelLifecycleId={props.novelLifecycleId}
          chapterLifecycleId={props.chapterLifecycleId} canApply={props.canApply} onProposalAccepted={props.onProposalAccepted} />;
      case 'consistency':
        return <ConsistencyChecker novel={props.novel ?? null} currentChapter={props.currentChapter ?? null}
          content={currentContent} onError={props.onError ?? (() => {})} />;
      case 'plot':
        return <PlotOptionsGenerator novelId={novelId} chapterId={chapterId} currentContent={currentContent}
          onPlotSelected={props.onPlotSelected ?? (() => {})} onPlotSelectedAndContinue={props.onPlotSelectedAndContinue} onError={props.onError ?? (() => {})} />;
      case 'research':
        return <ResearchAssistant novelId={novelId} onError={props.onError ?? (() => {})} />;
      default:
        return null;
    }
  };

  return <Box sx={{ height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column' }}>
    <Box sx={{ px: 2, py: 1, borderBottom: 1, borderColor: 'divider' }}>
      <Typography variant="subtitle2">创作对话</Typography>
      <Typography variant="caption" color="text.secondary">{chapterTitle ? `当前：${chapterTitle}` : '请先选择章节'} · 本书对话自动保存</Typography>
    </Box>
    {error && <Alert severity="warning" sx={{ borderRadius: 0 }} onClose={() => setError('')}
      action={<Button color="inherit" onClick={() => setAttempt((value) => value + 1)}>刷新对话</Button>}>{error}</Alert>}
    <Box ref={scrollRef} role="log" aria-label="创作对话记录" aria-live="polite"
      onScroll={(event) => { const box = event.currentTarget; followBottom.current = box.scrollHeight - box.scrollTop - box.clientHeight < 80; }}
      sx={{ flex: 1, minHeight: 0, overflow: 'auto', px: 2, py: 2 }}>
      {loading && <Typography role="status">正在恢复对话…</Typography>}
      {hasMore && <Button fullWidth disabled={loadingMore} onClick={() => void loadMore()}>加载更早对话</Button>}
      {!loading && !turns.length && <Box sx={{ py: 3 }}>
        <Typography variant="h6" gutterBottom>一起把故事写下去</Typography>
        <Typography variant="body2" color="text.secondary">讨论人物的动机，推敲下一幕，或让 AI 接着写。交流会留在这里。</Typography>
      </Box>}
      {turns.map((turn) => renderTurn(turn))}
      {actions.map((action) => <ActionCard key={action.id} state={action} onClose={closeAction}>{renderAction(action)}</ActionCard>)}
    </Box>
    <Box sx={{ p: 1.5, borderTop: 1, borderColor: 'divider', bgcolor: 'background.paper' }}>
      <TextField fullWidth multiline minRows={2} maxRows={5} label="和 Nai 聊聊" value={draft}
        placeholder="例如：接着往下写 / 这个世界魔法要付代价 / 他为什么要隐瞒身份"
        slotProps={{ htmlInput: { maxLength: 4000 } }} onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.nativeEvent.isComposing) { event.preventDefault(); void send(); } }} />
      <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', mt: 1 }}>
        <Typography variant="caption" color={chapterId ? 'text.secondary' : 'warning.main'}>
          {chapterId ? 'Nai 会自己判断该回答、整理设定还是起草正文' : '正在准备第 1 章，稍等一下就能发送…'}
        </Typography>
        <Box sx={{ flex: 1 }} />
        <IconButton aria-label="添加创作工具" title="创作工具" disabled={!chapterId} onClick={(event) => setMenuAnchor(event.currentTarget)}><AddIcon /></IconButton>
        <Menu anchorEl={menuAnchor} open={Boolean(menuAnchor)} onClose={() => setMenuAnchor(null)} slotProps={{ list: { 'aria-label': '创作工具列表' } }}>
          {ACTION_KINDS.map((item) => <MenuItem key={item.kind} onClick={() => openAction(item.kind)}>
            <ListItemIcon>{item.icon}</ListItemIcon>
            <ListItemText primary={item.label} secondary={item.hint} />
          </MenuItem>)}
        </Menu>
        {pending && <IconButton aria-label="停止回复" onClick={() => {
          void api.stopWritingTurn(novelId, pending.request_id).then((turn) => { if (mounted.current) { merge([turn]); controllerRef.current?.abort(); controllerRef.current = null; sendingRef.current = false; setSending(false); } }).catch(() => { if (mounted.current) setError('暂时无法停止，请稍后重试'); });
        }}><StopIcon /></IconButton>}
        <Button variant="contained" endIcon={<SendIcon />} disabled={loading || sending || Boolean(pending) || !chapterId || !draft.trim()} onClick={() => void send()}>发送</Button>
      </Box>
    </Box>
  </Box>;
});
const WritingChat = forwardRef<WritingChatRef, Props>(function WritingChat(props, ref) {
  return <WritingChatSession key={`${props.novelId}-${props.novelLifecycleId}`} {...props} ref={ref} />;
});
export default WritingChat;
