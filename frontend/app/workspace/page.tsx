'use client';

import {
  Fragment,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  Drawer,
  IconButton,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Menu,
  MenuItem,
  TextField,
  Typography,
 
  
  Tooltip,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import DeleteIcon from '@mui/icons-material/Delete';
import EditIcon from '@mui/icons-material/Edit';
import MenuIcon from '@mui/icons-material/Menu';
import MoreVertIcon from '@mui/icons-material/MoreVert';
import RedoIcon from '@mui/icons-material/Redo';
import SaveIcon from '@mui/icons-material/Save';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import UndoIcon from '@mui/icons-material/Undo';
import WarningIcon from '@mui/icons-material/Warning';
import ColorModeToggle from '@/components/layout/ColorModeToggle';
import ChapterConflictDialog, {
  type ConflictAction,
} from '@/components/workspace/ChapterConflictDialog';
import { api } from '@/lib/api';
import {
  useChapterSave,
  type ChapterDraftBackup,
  type ChapterSaveConflict,
} from '@/hooks/useChapterSave';
import { useEditHistory } from '@/hooks/useEditHistory';
import { useTextSelection } from '@/hooks/useTextSelection';
import { useWorkspaceKeyboardShortcuts } from '@/hooks/useWorkspaceKeyboardShortcuts';
import { countTextUnits } from '@/lib/textStats';
import { runAfterSave } from '@/lib/workspaceNavigation';
import type {
  Chapter,
  ChapterSummary,
  Novel,
  User,
} from '@/types';
import type { WritingChatRef } from '@/components/workspace/WritingChat';
import WritingChat from '@/components/workspace/WritingChat';
import ChapterMemory from '@/components/workspace/ChapterMemory';
import DraftRecovery from '@/components/workspace/DraftRecovery';
import StoryMemoryManager from '@/components/workspace/StoryMemoryManager';
import { useAuthenticatedUser } from '@/hooks/useAuthenticatedUser';
import StoryBibleManager from '@/components/novel/StoryBibleManager';
import WorldviewEditor from '@/components/novel/WorldviewEditor';
import ProjectInfoPanel from '@/components/workspace/ProjectInfoPanel';
import FolderOpenIcon from '@mui/icons-material/FolderOpen';
import MenuBookIcon from '@mui/icons-material/MenuBook';
import DescriptionOutlinedIcon from '@mui/icons-material/DescriptionOutlined';
import CloseIcon from '@mui/icons-material/Close';
import AutoSaver from '@/components/workspace/AutoSaver';
import CharacterStats from '@/components/workspace/CharacterStats';
import StyleManager from '@/components/workspace/StyleManager';

const DRAWER_WIDTH = 228;
const AI_PANEL_WIDTH = 390;
const CHAPTER_PAGE_SIZE = 50;

function toChapterSummary(chapter: Chapter): ChapterSummary {
  return {
    id: chapter.id,
    novel_id: chapter.novel_id,
    chapter_number: chapter.chapter_number,
    title: chapter.title,
    word_count: chapter.word_count,
    version: chapter.version,
    created_at: chapter.created_at,
    updated_at: chapter.updated_at,
  };
}

function mergeChapterSummaries(
  current: ChapterSummary[],
  incoming: ChapterSummary[],
): ChapterSummary[] {
  const byId = new Map(current.map((chapter) => [chapter.id, chapter]));
  for (const chapter of incoming) byId.set(chapter.id, chapter);
  return Array.from(byId.values()).sort(
    (left, right) => left.chapter_number - right.chapter_number,
  );
}

interface ChapterNavigatorProps {
  chapters: ChapterSummary[];
  total: number;
  currentChapterId: number | null;
  hasMore: boolean;
  loadingMore: boolean;
  onCreate: () => void;
  onSelect: (chapterId: number) => void;
  onMenuOpen: (event: React.MouseEvent<HTMLElement>, chapter: ChapterSummary) => void;
  onLoadMore: () => void;
}

function ChapterNavigator({
  chapters,
  total,
  currentChapterId,
  hasMore,
  loadingMore,
  onCreate,
  onSelect,
  onMenuOpen,
  onLoadMore,
}: ChapterNavigatorProps) {
  return (
    <Box sx={{ p: 1, height: '100%', overflow: 'auto' }}>
      <Box sx={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <Typography variant="subtitle2" gutterBottom fontWeight="600">
          章节目录
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {chapters.length}/{total}
        </Typography>
      </Box>
      <Button
        fullWidth
        variant="contained"
        startIcon={<AddIcon />}
        onClick={onCreate}
        sx={{ mb: 2 }}
      >
        新建下一章
      </Button>
      <Divider sx={{ mb: 2 }} />

      {chapters.length === 0 ? (
        <Typography variant="body2" color="text.secondary" sx={{ py: 3, textAlign: 'center' }}>
          暂无章节
        </Typography>
      ) : (
        <List dense disablePadding>
          {chapters.map((chapter) => (
            <ListItem key={chapter.id} disablePadding secondaryAction={
              <IconButton size="small" aria-label={`管理第${chapter.chapter_number}章`} onClick={(event) => { event.stopPropagation(); onMenuOpen(event, chapter); }}><MoreVertIcon fontSize="small" /></IconButton>
            }>
              <ListItemButton selected={currentChapterId === chapter.id} onClick={() => onSelect(chapter.id)} sx={{ py: 0.5, pl: 1, pr: 4, borderRadius: 0, borderLeft: '2px solid', borderColor: currentChapterId === chapter.id ? 'primary.main' : 'transparent' }}>
                <DescriptionOutlinedIcon sx={{ fontSize: 16, mr: 1, color: 'text.secondary' }} />
                <ListItemText primary={`${String(chapter.chapter_number).padStart(2, '0')}  ${chapter.title}`} secondary={`${(chapter.word_count || 0).toLocaleString()} 字`}
                  primaryTypographyProps={{ noWrap: true, fontSize: 13 }} secondaryTypographyProps={{ fontSize: 11 }} />
              </ListItemButton>
            </ListItem>
          ))}
        </List>
      )}

      {hasMore && (
        <Button fullWidth onClick={onLoadMore} disabled={loadingMore} sx={{ mt: 1 }}>
          {loadingMore ? '加载中...' : '加载更多章节'}
        </Button>
      )}
    </Box>
  );
}

function WorkspaceSession({ authenticatedUser }: { authenticatedUser: User }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const novelId = Number(searchParams.get('novel')) || 0;
  const requestedChapterId = Number(searchParams.get('chapter')) || 0;

  const [novel, setNovel] = useState<Novel | null>(null);
  const [chapters, setChapters] = useState<ChapterSummary[]>([]);
  const [chapterPage, setChapterPage] = useState(1);
  const [chapterTotal, setChapterTotal] = useState(0);
  const [hasMoreChapters, setHasMoreChapters] = useState(false);
  const [currentChapter, setCurrentChapter] = useState<Chapter | null>(null);
  const [content, setContent] = useState('');
  const [title, setTitle] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [novelTotalWords, setNovelTotalWords] = useState(0);
  const [error, setError] = useState('');
  const [conflictDialogOpen, setConflictDialogOpen] = useState(false);
  const [conflictServerChapter, setConflictServerChapter] = useState<Chapter | null>(null);
  const [conflictLoadingServer, setConflictLoadingServer] = useState(false);
  const [conflictActionLoading, setConflictActionLoading] = useState<ConflictAction | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [editorTab, setEditorTab] = useState<'chapter' | 'settings'>('chapter');
  const [openChapters, setOpenChapters] = useState<ChapterSummary[]>([]);
  useEffect(() => { setOpenChapters([]); setEditorTab('chapter'); }, [novelId]);
  useEffect(() => {
    if (!currentChapter) return;
    setOpenChapters((previous) => previous.some((item) => item.id === currentChapter.id)
      ? previous.map((item) => item.id === currentChapter.id ? toChapterSummary(currentChapter) : item)
      : [...previous, toChapterSummary(currentChapter)].slice(-10));
  }, [currentChapter]);
  useEffect(() => { setEditorTab('chapter'); }, [currentChapter?.id]);

  const [createChapterDialogOpen, setCreateChapterDialogOpen] = useState(false);
  const [newChapterTitle, setNewChapterTitle] = useState('');
  const [creatingChapter, setCreatingChapter] = useState(false);
  const [chapterMenuAnchor, setChapterMenuAnchor] = useState<HTMLElement | null>(null);
  const [selectedChapterForMenu, setSelectedChapterForMenu] = useState<ChapterSummary | null>(null);
  const [deleteChapterDialogOpen, setDeleteChapterDialogOpen] = useState(false);
  const [editChapterDialogOpen, setEditChapterDialogOpen] = useState(false);
  const [editChapterTitle, setEditChapterTitle] = useState('');
  const [deletingChapter, setDeletingChapter] = useState(false);
  const [updatingChapter, setUpdatingChapter] = useState(false);

  const { selectionStart, selectionEnd, selectedText, contentInputRef, handleTextSelection, clearSelection } = useTextSelection();
  useEffect(clearSelection, [novelId, requestedChapterId, clearSelection]);
  const [selectedStyleSampleId, setSelectedStyleSampleId] = useState<number | null>(null);
  const [plotDirectionHint, setPlotDirectionHint] = useState<string | null>(null);
  const aiWritingAssistantRef = useRef<WritingChatRef | null>(null);

  const novelRequestRef = useRef<{ id: number; controller: AbortController } | null>(null);
  const workspaceRequestRef = useRef<{ id: number; controller: AbortController } | null>(null);
  const loadMoreRequestRef = useRef<{ id: number; controller: AbortController } | null>(null);
  const conflictFetchControllerRef = useRef<AbortController | null>(null);
  const conflictMutationControllerRef = useRef<AbortController | null>(null);
  const requestSequenceRef = useRef(0);
  const skipNextWorkspaceLoadRef = useRef(false);

  const {
    canUndo,
    canRedo,
    addToHistory,
    undo,
    redo,
    clearHistory,
  } = useEditHistory({
    batchDelay: 400,
    maxHistorySize: 50,
    maxCharacterBudget: 5_000_000,
  });

  const currentChapterWordCountRef = useRef(currentChapter?.word_count ?? 0);
  currentChapterWordCountRef.current = currentChapter?.word_count ?? 0;

  const handleSaved = useCallback((
    snapshot: { chapterId: number; title: string; content: string },
    savedChapter: Chapter,
  ) => {
    const previousWordCount = currentChapterWordCountRef.current;
    currentChapterWordCountRef.current = savedChapter.word_count;
    setNovelTotalWords((total) =>
      Math.max(0, total + savedChapter.word_count - previousWordCount),
    );
    setCurrentChapter((previous) => {
      if (previous?.id !== snapshot.chapterId) return previous;
      return {
        ...savedChapter,
        title: snapshot.title,
        content: snapshot.content,
      };
    });
    setChapters((previous) =>
      mergeChapterSummaries(previous, [
        toChapterSummary({
          ...savedChapter,
          title: snapshot.title,
          content: snapshot.content,
        }),
      ]),
    );
    setError('');
  }, []);

  const handleDraftRestored = useCallback((draft: ChapterDraftBackup) => {
    setTitle(draft.title);
    setContent(draft.content);
    clearHistory(draft.content);
    setError('');
  }, [clearHistory]);

  const handleSaveConflict = useCallback((nextConflict: ChapterSaveConflict) => {
    setConflictDialogOpen(true);
    setConflictServerChapter(null);
    setConflictLoadingServer(true);
    setConflictActionLoading(null);
    conflictFetchControllerRef.current?.abort();
    const controller = new AbortController();
    conflictFetchControllerRef.current = controller;

    void api
      .getChapter(novelId, nextConflict.snapshot.chapterId, {
        signal: controller.signal,
      })
      .then((serverChapter) => {
        if (controller.signal.aborted) return;
        setConflictServerChapter(serverChapter);
        setConflictLoadingServer(false);
      })
      .catch((loadError) => {
        if (controller.signal.aborted || (loadError instanceof Error && loadError.name === 'AbortError')) return;
        setConflictLoadingServer(false);
        setError(loadError instanceof Error ? loadError.message : '加载服务端章节失败');
      });
  }, [novelId]);

  const {
    status: saveStatus,
    isDirty,
    isSaving,
    lastSavedAt,
    conflict,
    isOffline,
    hasLocalBackup,
    recoveryDrafts,
    identityReady,
    saveNow,
    overwriteConflict,
    adoptServerChapter,
  } = useChapterSave({
    novelId,
    userId: authenticatedUser && authenticatedUser.id === novel?.user_id && novel?.id === novelId ? authenticatedUser.id : null,
    novelLifecycleId: novel?.id === novelId ? novel.rag_lifecycle_id : undefined,
    chapter: currentChapter,
    title,
    content,
    onSaved: handleSaved,
    onError: setError,
    onConflict: handleSaveConflict,
    onDraftRestored: handleDraftRestored,
  });
  const dirtyRef = useRef(isDirty);
  const saveNowRef = useRef(saveNow);
  const currentChapterRef = useRef(currentChapter);
  dirtyRef.current = isDirty;
  saveNowRef.current = saveNow;
  currentChapterRef.current = currentChapter;
  const workspaceIdentity = `${authenticatedUser?.id}:${novelId}:${novel?.rag_lifecycle_id}:${currentChapter?.id}:${currentChapter?.rag_lifecycle_id}`;
  const workspaceIdentityRef = useRef(workspaceIdentity);
  workspaceIdentityRef.current = workspaceIdentity;
  useEffect(() => {
    conflictFetchControllerRef.current?.abort(); conflictMutationControllerRef.current?.abort();
    setConflictDialogOpen(false); setConflictServerChapter(null); setConflictActionLoading(null);
    return () => { conflictFetchControllerRef.current?.abort(); conflictMutationControllerRef.current?.abort(); };
  }, [workspaceIdentity]);

  const runAfterCurrentSave = useCallback(<T,>(action: () => Promise<T> | T) => {
    return runAfterSave({
      isDirty,
      save: () => {
        if (conflict) {
          setConflictDialogOpen(true);
          throw new Error(conflict.message || '章节版本冲突，请先处理');
        }
        return saveNow('manual');
      },
      action,
    });
  }, [conflict, isDirty, saveNow]);

  useEffect(() => {
    if (!novelId) {
      setNovel(null);
      setError('缺少小说参数');
      return;
    }

    const requestId = requestSequenceRef.current + 1;
    requestSequenceRef.current = requestId;
    novelRequestRef.current?.controller.abort();
    const controller = new AbortController();
    novelRequestRef.current = { id: requestId, controller };

    void api
      .getNovel(novelId, { signal: controller.signal })
      .then((data) => {
        if (novelRequestRef.current?.id === requestId) setNovel(data);
      })
      .catch((loadError) => {
        if (loadError instanceof Error && loadError.name === 'AbortError') return;
        if (novelRequestRef.current?.id === requestId) {
          setError(loadError instanceof Error ? loadError.message : '加载小说失败');
        }
      });

    return () => controller.abort();
  }, [novelId]);

  const loadWorkspace = useCallback(async () => {
    if (!novelId) return;

    const activeChapter = currentChapterRef.current;
    if (
      skipNextWorkspaceLoadRef.current &&
      activeChapter?.novel_id === novelId &&
      activeChapter.id === requestedChapterId
    ) {
      skipNextWorkspaceLoadRef.current = false;
      setLoading(false);
      return;
    }

    const isLeavingActiveChapter = Boolean(
      activeChapter &&
      (activeChapter.novel_id !== novelId || activeChapter.id !== requestedChapterId),
    );
    if (isLeavingActiveChapter && dirtyRef.current) {
      try {
        await saveNowRef.current('manual');
      } catch {
        if (activeChapter) {
          skipNextWorkspaceLoadRef.current = true;
          router.replace(
            `/workspace?novel=${activeChapter.novel_id}&chapter=${activeChapter.id}`,
          );
        }
        setLoading(false);
        return;
      }
    }

    const requestId = requestSequenceRef.current + 1;
    requestSequenceRef.current = requestId;
    workspaceRequestRef.current?.controller.abort();
    const controller = new AbortController();
    workspaceRequestRef.current = { id: requestId, controller };
    loadMoreRequestRef.current?.controller.abort();
    loadMoreRequestRef.current = null;
    setLoadingMore(false);
    setLoading(true);
    setError('');

    try {
      const [summaryPage, chapterDetail, novelStatistics] = await Promise.all([
        api.getChapterSummaries(
          novelId,
          { page: 1, pageSize: CHAPTER_PAGE_SIZE },
          { signal: controller.signal },
        ),
        requestedChapterId
          ? api.getChapter(novelId, requestedChapterId, { signal: controller.signal })
          : Promise.resolve(null),
        api.getNovelStatistics({ signal: controller.signal }),
      ]);

      if (workspaceRequestRef.current?.id !== requestId) return;

      const initialSummaries = chapterDetail
        ? mergeChapterSummaries(summaryPage.items, [toChapterSummary(chapterDetail)])
        : summaryPage.items;
      setChapters(initialSummaries);
      setChapterPage(summaryPage.page);
      setChapterTotal(summaryPage.total);
      setHasMoreChapters(summaryPage.has_more);
      setNovelTotalWords(
        novelStatistics.find((item) => item.novel_id === novelId)?.total_words ?? 0,
      );

      if (chapterDetail) {
        setCurrentChapter(chapterDetail);
        setTitle(chapterDetail.title);
        setContent(chapterDetail.content);
        clearHistory(chapterDetail.content);
      } else if (summaryPage.total === 0) {
        // 空项目应当能直接开写：没有章节时自动建第 1 章，而不是把作者挡在禁用按钮前。
        const first = await api.createNextChapter(novelId, { content: '' });
        if (workspaceRequestRef.current?.id !== requestId) return;
        setChapters([toChapterSummary(first)]);
        setChapterTotal(1);
        setCurrentChapter(first);
        setTitle(first.title);
        setContent(first.content);
        clearHistory(first.content);
        skipNextWorkspaceLoadRef.current = true;
        router.replace(`/workspace?novel=${novelId}&chapter=${first.id}`);
      } else {
        setCurrentChapter(null);
        setTitle('');
        setContent('');
        clearHistory('');
      }
    } catch (loadError) {
      if (loadError instanceof Error && loadError.name === 'AbortError') return;
      if (workspaceRequestRef.current?.id === requestId) {
        setError(loadError instanceof Error ? loadError.message : '加载工作台失败');
      }
    } finally {
      if (workspaceRequestRef.current?.id === requestId) setLoading(false);
    }
  }, [clearHistory, novelId, requestedChapterId, router]);

  useEffect(() => {
    void loadWorkspace();
    return () => {
      workspaceRequestRef.current?.controller.abort();
      loadMoreRequestRef.current?.controller.abort();
      conflictFetchControllerRef.current?.abort();
    };
  }, [loadWorkspace]);

  const handleLoadMore = useCallback(async () => {
    if (!novelId || loadingMore || !hasMoreChapters) return;
    const requestId = requestSequenceRef.current + 1;
    requestSequenceRef.current = requestId;
    loadMoreRequestRef.current?.controller.abort();
    const controller = new AbortController();
    loadMoreRequestRef.current = { id: requestId, controller };
    const requestNovelId = novelId;
    setLoadingMore(true);
    try {
      const nextPage = chapterPage + 1;
      const result = await api.getChapterSummaries(
        novelId,
        { page: nextPage, pageSize: CHAPTER_PAGE_SIZE },
        { signal: controller.signal },
      );
      if (
        loadMoreRequestRef.current?.id !== requestId ||
        requestNovelId !== novelId
      ) return;
      setChapters((previous) => mergeChapterSummaries(previous, result.items));
      setChapterPage(result.page);
      setChapterTotal(result.total);
      setHasMoreChapters(result.has_more);
    } catch (loadError) {
      if (loadError instanceof Error && loadError.name === 'AbortError') return;
      if (loadMoreRequestRef.current?.id !== requestId) return;
      setError(loadError instanceof Error ? loadError.message : '加载更多章节失败');
    } finally {
      if (loadMoreRequestRef.current?.id === requestId) {
        loadMoreRequestRef.current = null;
        setLoadingMore(false);
      }
    }
  }, [chapterPage, hasMoreChapters, loadingMore, novelId]);

  const handleSave = useCallback(async () => {
    if (conflict) {
      setConflictDialogOpen(true);
      return;
    }
    try {
      await saveNow('manual');
    } catch {
      // 保存 Hook 已提供可操作的错误信息。
    }
  }, [conflict, saveNow]);

  const applyServerChapterLocally = useCallback((serverChapter: Chapter) => {
    if (!identityReady || serverChapter.novel_id !== novelId || serverChapter.id !== currentChapterRef.current?.id || serverChapter.rag_lifecycle_id !== currentChapterRef.current?.rag_lifecycle_id) return;
    const previousWordCount = currentChapterWordCountRef.current;
    currentChapterWordCountRef.current = serverChapter.word_count;
    setNovelTotalWords((total) =>
      Math.max(0, total + serverChapter.word_count - previousWordCount),
    );
    setCurrentChapter(serverChapter);
    setTitle(serverChapter.title);
    setContent(serverChapter.content);
    clearHistory(serverChapter.content);
    setChapters((previous) =>
      mergeChapterSummaries(previous, [toChapterSummary(serverChapter)]),
    );
    setError('');
  }, [clearHistory, identityReady, novelId]);

  const handleProposalAccepted = useCallback((savedChapter: Chapter) => {
    if (!identityReady || savedChapter.novel_id !== novelId) return;
    setChapters((previous) => mergeChapterSummaries(previous, [toChapterSummary(savedChapter)]));
    if (savedChapter.id === currentChapterRef.current?.id) {
      if (dirtyRef.current) {
        setError('候选已保存到服务器。采纳期间你又修改了本机正文，新稿已保留；请保存并核对版本冲突。');
        return;
      }
      adoptServerChapter(savedChapter);
      applyServerChapterLocally(savedChapter);
    } else {
      setChapterTotal((total) => total + 1);
      if (dirtyRef.current) {
        setError('候选已另存为新章节，本机新稿仍保留。保存后可从目录打开新章。');
        return;
      }
      router.push(`/workspace?novel=${novelId}&chapter=${savedChapter.id}`);
    }
  }, [adoptServerChapter, applyServerChapterLocally, identityReady, novelId, router]);

  const handleAcceptServerConflict = useCallback(() => {
    if (!identityReady || !conflictServerChapter) return;
    setConflictActionLoading('accept');
    adoptServerChapter(conflictServerChapter);
    applyServerChapterLocally(conflictServerChapter);
    setConflictDialogOpen(false);
    setConflictActionLoading(null);
  }, [adoptServerChapter, applyServerChapterLocally, conflictServerChapter, identityReady]);

  const handleOverwriteServerConflict = useCallback(async () => {
    if (!conflict || !conflictServerChapter) return;
    setConflictActionLoading('overwrite');
    try {
      await overwriteConflict(conflictServerChapter.version);
      setConflictDialogOpen(false);
    } catch (overwriteError) {
      setError(overwriteError instanceof Error ? overwriteError.message : '覆盖服务端版本失败');
    } finally {
      setConflictActionLoading(null);
    }
  }, [conflict, conflictServerChapter, overwriteConflict]);

  const handleCopyToNewChapter = useCallback(async () => {
    if (!identityReady || !conflict || !conflictServerChapter || conflictServerChapter.rag_lifecycle_id !== currentChapterRef.current?.rag_lifecycle_id) return;
    const identity = workspaceIdentityRef.current;
    const controller = new AbortController(); conflictMutationControllerRef.current = controller;
    setConflictActionLoading('copy');
    try {
      const sourceTitle = conflict.snapshot.title.trim() || '未命名章节';
      const newChapter = await api.createNextChapter(novelId, {
        title: `${sourceTitle}（冲突副本）`,
        content: conflict.snapshot.content,
      }, { signal: controller.signal });
      if (controller.signal.aborted || workspaceIdentityRef.current !== identity) return;
      adoptServerChapter(conflictServerChapter);
      applyServerChapterLocally(conflictServerChapter);
      // 本地版本已复制到新章，当前章随即采纳服务端版本，离场不再触发旧冲突保存。
      dirtyRef.current = false;
      setChapters((previous) =>
        mergeChapterSummaries(previous, [toChapterSummary(newChapter)]),
      );
      setChapterTotal((total) => total + 1);
      setConflictDialogOpen(false);
      router.push(`/workspace?novel=${novelId}&chapter=${newChapter.id}`);
    } catch (copyError) {
      if (!controller.signal.aborted && workspaceIdentityRef.current === identity) setError(copyError instanceof Error ? copyError.message : '另存新章节失败');
    } finally {
      if (workspaceIdentityRef.current === identity) setConflictActionLoading(null);
    }
  }, [
    identityReady,
    adoptServerChapter,
    applyServerChapterLocally,
    conflict,
    conflictServerChapter,
    novelId,
    router,
  ]);

  const handleChapterSelected = useCallback(async (nextChapterId: number) => {
    setEditorTab('chapter');
    if (nextChapterId === currentChapter?.id) {
      setMobileOpen(false);
      return;
    }
    try {
      await runAfterCurrentSave(() => {
        setMobileOpen(false);
        router.push(`/workspace?novel=${novelId}&chapter=${nextChapterId}`);
      });
    } catch {
      // 保存或导航失败时保留当前章节和草稿。
    }
  }, [currentChapter?.id, novelId, router, runAfterCurrentSave]);

  const handleContentGenerated = useCallback((newContent: string) => {
    setContent(newContent);
    addToHistory(newContent, { immediate: true });
  }, [addToHistory]);

  const formatPlotDirection = useCallback((option: {
    title: string;
    summary: string;
    impact?: string | null;
    risk?: string | null;
  }) => {
    return [
      option.title,
      option.summary,
      option.impact ? `影响：${option.impact}` : null,
      option.risk ? `风险：${option.risk}` : null,
    ].filter(Boolean).join('；');
  }, []);

  const handlePlotSelected = useCallback((option: {
    id: number;
    title: string;
    summary: string;
    impact?: string | null;
    risk?: string | null;
  }) => {
    setPlotDirectionHint(formatPlotDirection(option));
  }, [formatPlotDirection]);

  const handlePlotSelectedAndContinue = useCallback((option: {
    id: number;
    title: string;
    summary: string;
    impact?: string | null;
    risk?: string | null;
  }) => {
    const instruction = formatPlotDirection(option);
    setPlotDirectionHint(instruction);
    aiWritingAssistantRef.current?.triggerContinue(instruction);
  }, [formatPlotDirection]);

  const handleCreateChapterOpen = useCallback(() => {
    setNewChapterTitle('');
    setCreateChapterDialogOpen(true);
  }, []);

  const handleCreateChapter = useCallback(async () => {
    setCreatingChapter(true);
    try {
      await runAfterCurrentSave(async () => {
        const newChapter = await api.createNextChapter(novelId, {
          title: newChapterTitle.trim() || undefined,
          content: '',
        });
        setCreateChapterDialogOpen(false);
        setNewChapterTitle('');
        setChapters((previous) => mergeChapterSummaries(previous, [toChapterSummary(newChapter)]));
        setChapterTotal((total) => total + 1);
        router.push(`/workspace?novel=${novelId}&chapter=${newChapter.id}`);
      });
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : '创建章节失败');
    } finally {
      setCreatingChapter(false);
    }
  }, [newChapterTitle, novelId, router, runAfterCurrentSave]);

  const handleBack = useCallback(async () => {
    try {
      await runAfterCurrentSave(() => router.back());
    } catch {
      // 保存失败时留在当前工作台。
    }
  }, [router, runAfterCurrentSave]);

  const handleChapterMenuOpen = useCallback((
    event: React.MouseEvent<HTMLElement>,
    chapter: ChapterSummary,
  ) => {
    event.stopPropagation();
    setChapterMenuAnchor(event.currentTarget);
    setSelectedChapterForMenu(chapter);
  }, []);

  const handleChapterMenuClose = useCallback(() => {
    setChapterMenuAnchor(null);
    setSelectedChapterForMenu(null);
  }, []);

  const handleEditChapterOpen = useCallback(() => {
    if (!selectedChapterForMenu) return;
    setEditChapterTitle(selectedChapterForMenu.title);
    setEditChapterDialogOpen(true);
    setChapterMenuAnchor(null);
  }, [selectedChapterForMenu]);

  const handleUpdateChapter = useCallback(async () => {
    if (!selectedChapterForMenu || !editChapterTitle.trim()) {
      setError('章节标题不能为空');
      return;
    }
    setUpdatingChapter(true);
    try {
      if (selectedChapterForMenu.id === currentChapter?.id) {
        setTitle(editChapterTitle.trim());
      } else {
        const updated = await api.updateChapter(
          novelId,
          selectedChapterForMenu.id,
          {
            title: editChapterTitle.trim(),
            expected_version: selectedChapterForMenu.version,
          },
        );
        setChapters((previous) =>
          mergeChapterSummaries(previous, [toChapterSummary(updated)]),
        );
      }
      setEditChapterDialogOpen(false);
      setSelectedChapterForMenu(null);
      setEditChapterTitle('');
    } catch (updateError) {
      setError(updateError instanceof Error ? updateError.message : '更新章节失败');
    } finally {
      setUpdatingChapter(false);
    }
  }, [currentChapter?.id, editChapterTitle, novelId, selectedChapterForMenu]);

  const handleDeleteChapterOpen = useCallback(() => {
    setDeleteChapterDialogOpen(true);
    setChapterMenuAnchor(null);
  }, []);

  const handleDeleteChapter = useCallback(async () => {
    if (!selectedChapterForMenu) return;
    const deletingId = selectedChapterForMenu.id;
    setDeletingChapter(true);
    try {
      await api.deleteChapter(novelId, deletingId);
      const remaining = chapters.filter((chapter) => chapter.id !== deletingId);
      setChapters(remaining);
      setOpenChapters((previous) => previous.filter((chapter) => chapter.id !== deletingId));
      setChapterTotal((total) => Math.max(0, total - 1));
      setDeleteChapterDialogOpen(false);
      setSelectedChapterForMenu(null);

      if (currentChapter?.id === deletingId) {
        const fallback = remaining[0];
        setCurrentChapter(null);
        setTitle('');
        setContent('');
        clearHistory('');
        router.push(
          fallback
            ? `/workspace?novel=${novelId}&chapter=${fallback.id}`
            : `/workspace?novel=${novelId}`,
        );
      }
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : '删除章节失败');
    } finally {
      setDeletingChapter(false);
    }
  }, [chapters, clearHistory, currentChapter?.id, novelId, router, selectedChapterForMenu]);

  const handleUndo = useCallback(() => {
    const previous = undo();
    if (previous !== null) setContent(previous);
  }, [undo]);

  const handleRedo = useCallback(() => {
    const next = redo();
    if (next !== null) setContent(next);
  }, [redo]);

  const currentChapterIndex = chapters.findIndex(
    (chapter) => chapter.id === currentChapter?.id,
  );
  const hasPreviousChapter = currentChapterIndex > 0;
  const hasNextChapter =
    currentChapterIndex >= 0 && currentChapterIndex < chapters.length - 1;

  const handlePreviousChapter = useCallback(() => {
    if (!hasPreviousChapter) return;
    const previousChapter = chapters[currentChapterIndex - 1];
    void handleChapterSelected(previousChapter.id);
  }, [chapters, currentChapterIndex, handleChapterSelected, hasPreviousChapter]);

  const handleNextChapter = useCallback(() => {
    if (!hasNextChapter) return;
    const nextChapter = chapters[currentChapterIndex + 1];
    void handleChapterSelected(nextChapter.id);
  }, [chapters, currentChapterIndex, handleChapterSelected, hasNextChapter]);

  useWorkspaceKeyboardShortcuts({
    enabled:
      !loading &&
      editorTab === 'chapter' &&
      Boolean(currentChapter) &&
      !createChapterDialogOpen &&
      !editChapterDialogOpen &&
      !deleteChapterDialogOpen &&
      !chapterMenuAnchor,
    canUndo,
    canRedo,
    hasPreviousChapter,
    hasNextChapter,
    onSave: () => void handleSave(),
    onUndo: handleUndo,
    onRedo: handleRedo,
    onPreviousChapter: handlePreviousChapter,
    onNextChapter: handleNextChapter,
  });

  const chapterNavigator = (
    <ChapterNavigator
      chapters={chapters}
      total={chapterTotal}
      currentChapterId={currentChapter?.id ?? null}
      hasMore={hasMoreChapters}
      loadingMore={loadingMore}
      onCreate={handleCreateChapterOpen}
      onSelect={(chapterId) => void handleChapterSelected(chapterId)}
      onMenuOpen={handleChapterMenuOpen}
      onLoadMore={() => void handleLoadMore()}
    />
  );

  const authorVerified = Boolean(authenticatedUser && novel && authenticatedUser.id === novel.user_id && novel.id === novelId);
  const settingsContent = authorVerified && novel && <Box sx={{ p: { xs: 2, md: 3 }, maxWidth: 900, mx: 'auto' }}>
    <Typography variant="h5" gutterBottom>项目与设定</Typography>
    <ProjectInfoPanel key={`${novelId}-${novel.updated_at ?? ''}`} novel={novel} onNovelChange={setNovel} />
    <Divider sx={{ my: 3 }} />
    <WorldviewEditor key={novelId} novel={novel} /><StoryBibleManager novelId={novelId} />
    {novel.rag_lifecycle_id && <StoryMemoryManager novelId={novelId} novelLifecycleId={novel.rag_lifecycle_id} chapterId={currentChapter?.id ?? null} chapterNumber={currentChapter?.chapter_number ?? null} />}
    <Divider sx={{ my: 3 }} />
    <ChapterMemory novelId={novelId} chapterId={currentChapter?.id ?? null} currentVersion={currentChapter?.version ?? 1}
      novelLifecycleId={novel?.rag_lifecycle_id} chapterLifecycleId={currentChapter?.rag_lifecycle_id}
      currentContent={content} canRestore={identityReady && !isDirty && !isSaving} onVersionRestored={handleProposalAccepted} />
    <Divider sx={{ my: 3 }} />
    <StyleManager novelId={novelId} selectedStyleSampleId={selectedStyleSampleId} onStyleSampleSelected={setSelectedStyleSampleId} onError={setError} />
    <Divider sx={{ my: 3 }} />
    <CharacterStats novel={novel} currentContent={content} />
  </Box>;


  return (
    <Fragment>
      <Drawer variant="temporary" open={mobileOpen} onClose={() => setMobileOpen(false)}
        sx={{ '& .MuiDrawer-paper': { width: DRAWER_WIDTH } }}>{chapterNavigator}</Drawer>
      <Box sx={{ height: '100dvh', display: 'flex', flexDirection: 'column', overflow: 'hidden', bgcolor: 'background.default',
        '& .MuiButton-root': { borderRadius: 1 }, '& .MuiCard-root': { boxShadow: 'none' } }}>
        <Box component="header" sx={{ height: 42, flexShrink: 0, display: 'flex', alignItems: 'center', px: 1, gap: 1, bgcolor: 'background.paper', borderBottom: 1, borderColor: 'divider' }}>
          <IconButton size="small" aria-label="返回小说" onClick={() => void handleBack()}><ArrowBackIcon fontSize="small" /></IconButton>
          <Typography variant="subtitle2" sx={{ color: 'primary.main', mr: 1 }}>NAI</Typography>
          <Typography variant="body2" noWrap sx={{ flex: 1 }}>{novel?.title || '创作工作区'}</Typography>
          <Button size="small" startIcon={<SaveIcon />} aria-label={isSaving ? '保存中' : '保存章节'} disabled={isSaving || !isDirty} onClick={() => void handleSave()}>保存</Button>
          <ColorModeToggle />
        </Box>
        <Box sx={{ flex: 1, minHeight: 0, display: 'flex' }}>
          <Box component="nav" aria-label="工作区活动栏" sx={{ width: 46, flexShrink: 0, display: { xs: 'none', md: 'flex' }, flexDirection: 'column', alignItems: 'center', gap: 1, py: 1, bgcolor: 'background.paper', borderRight: 1, borderColor: 'divider' }}>
            <Tooltip title="章节资源管理器" placement="right"><IconButton aria-label="切换章节目录" color={sidebarOpen ? 'primary' : 'default'} onClick={() => setSidebarOpen((value) => !value)}><FolderOpenIcon /></IconButton></Tooltip>
            <Tooltip title="设定与伏笔" placement="right"><IconButton aria-label="打开设定标签" color={editorTab === 'settings' ? 'primary' : 'default'} onClick={() => setEditorTab('settings')}><MenuBookIcon /></IconButton></Tooltip>
            <Tooltip title="创作对话" placement="right"><IconButton aria-label="查看创作对话" color="primary" disabled><SmartToyIcon /></IconButton></Tooltip>
          </Box>
          {sidebarOpen && <Box component="aside" aria-label="章节资源管理器" sx={{ width: DRAWER_WIDTH, flexShrink: 0, display: { xs: 'none', md: 'flex' }, flexDirection: 'column', minHeight: 0, borderRight: 1, borderColor: 'divider', bgcolor: 'background.paper' }}>
            <Button size="small" startIcon={<MenuBookIcon />} sx={{ justifyContent: 'flex-start', px: 2, py: 1 }} onClick={() => setEditorTab('settings')}>设定与伏笔</Button>
            <Box sx={{ flex: 1, minHeight: 0 }}>{chapterNavigator}</Box>
          </Box>}
          <Box sx={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: { xs: 'column', md: 'row' }, minHeight: 0 }}>
            <Box component="main" sx={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
              <Box sx={{ display: 'flex', alignItems: 'center', minHeight: 39, flexShrink: 0, borderBottom: 1, borderColor: 'divider', bgcolor: 'background.paper', overflow: 'auto' }}>
                <IconButton size="small" aria-label="打开章节列表" sx={{ display: { md: 'none' } }} onClick={() => setMobileOpen(true)}><MenuIcon fontSize="small" /></IconButton>
                <Box role="tablist" aria-label="编辑文档" sx={{ display: 'flex', minWidth: 0 }}>
                  {openChapters.map((chapter) => <Box key={chapter.id} sx={{ display: 'flex', alignItems: 'center', borderRight: 1, borderTop: 2, borderColor: editorTab === 'chapter' && currentChapter?.id === chapter.id ? 'primary.main' : 'divider', bgcolor: editorTab === 'chapter' && currentChapter?.id === chapter.id ? 'background.default' : 'transparent' }}>
                    <Button role="tab" aria-selected={editorTab === 'chapter' && currentChapter?.id === chapter.id} size="small" startIcon={<DescriptionOutlinedIcon fontSize="small" />} sx={{ maxWidth: 180, whiteSpace: 'nowrap', color: 'text.primary' }} onClick={() => void handleChapterSelected(chapter.id)}><Box component="span" sx={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{chapter.title}{currentChapter?.id === chapter.id && isDirty ? ' •' : ''}</Box></Button>
                    {chapter.id !== currentChapter?.id && <IconButton size="small" aria-label={`关闭标签${chapter.title}`} onClick={() => setOpenChapters((previous) => previous.filter((item) => item.id !== chapter.id))}><CloseIcon sx={{ fontSize: 14 }} /></IconButton>}
                  </Box>)}
                  <Button role="tab" aria-selected={editorTab === 'settings'} size="small" startIcon={<MenuBookIcon />} sx={{ minWidth: 115, borderTop: 2, borderRadius: 0, borderColor: editorTab === 'settings' ? 'primary.main' : 'transparent' }} onClick={() => setEditorTab('settings')}>设定与伏笔</Button>
                </Box>
              </Box>
              <Box sx={{ display: editorTab === 'settings' ? 'block' : 'none', flex: 1, minHeight: 0, overflow: 'auto' }}>{settingsContent}</Box>
              <Box sx={{ display: editorTab === 'chapter' ? 'block' : 'none', flex: 1, minHeight: 0, overflow: 'auto', px: { xs: 2, md: 4 }, py: 2 }}>
                {error && <Alert severity="error" onClose={() => setError('')} sx={{ mb: 2 }}>{error}</Alert>}
                <DraftRecovery drafts={recoveryDrafts} />
                {!identityReady && currentChapter && <Alert severity="info">正在核验作者与章节身份；若长时间未完成，请重新登录并打开作品。</Alert>}
                {isOffline && isDirty && <Alert severity="warning" sx={{ mb: 2 }}>当前离线，{hasLocalBackup ? '草稿已保留在本机' : '正在保存本地草稿'}，恢复连接后会重试保存。</Alert>}
                {loading ? <CircularProgress size={24} /> : currentChapter ? <Box data-workspace-editor sx={{ maxWidth: 860, mx: 'auto' }}>
                  <Typography variant="caption" color="text.secondary">正文 / 第 {currentChapter.chapter_number} 章</Typography>
                  <TextField disabled={!identityReady} fullWidth variant="standard" label="章节标题" value={title} onChange={(event) => setTitle(event.target.value)} sx={{ mb: 2, mt: 1, '& .MuiInputBase-root': { fontSize: '1.4rem' } }} />
                  <TextField disabled={!identityReady} fullWidth multiline variant="standard" minRows={10} label="章节内容" value={content}
                    onChange={(event) => { const nextContent = event.target.value; setContent(nextContent); clearSelection(); addToHistory(nextContent); }}
                    onSelect={handleTextSelection} inputRef={contentInputRef} placeholder="开始写作…"
                    slotProps={{ input: { disableUnderline: true } }}
                    sx={{ '& .MuiInputBase-input': { fontSize: '1rem', lineHeight: 1.95, letterSpacing: '0.02em' } }} />
                </Box> : <Box sx={{ p: 3 }}><Typography>从左侧选择章节，开始创作。</Typography><Button startIcon={<AddIcon />} onClick={handleCreateChapterOpen}>新建下一章</Button></Box>}
              </Box>
            </Box>
            <Box component="aside" aria-label="AI 创作工作区" sx={{ width: { xs: '100%', md: AI_PANEL_WIDTH, xl: 440 }, height: { xs: '48%', md: '100%' }, minHeight: { xs: 270, md: 0 }, flexShrink: 0, display: 'flex', flexDirection: 'column', borderLeft: { md: 1 }, borderTop: { xs: 1, md: 0 }, borderColor: 'divider', bgcolor: 'background.paper' }}>
              <Box sx={{ flex: 1, minHeight: 0, display: 'block' }}>
                {authorVerified && novel && <WritingChat key={`${authenticatedUser?.id}-${novelId}-${novel.rag_lifecycle_id}`} ref={aiWritingAssistantRef} novelId={novelId} chapterId={currentChapter?.id ?? null} chapterTitle={title} currentContent={content} onContentGenerated={handleContentGenerated}
                  chapterVersion={currentChapter?.version} novelLifecycleId={novel.rag_lifecycle_id} chapterLifecycleId={currentChapter?.rag_lifecycle_id}
                  canApply={identityReady && !isDirty && !isSaving} onProposalAccepted={handleProposalAccepted}
                  onSettingsApplied={() => { void api.getNovel(novelId).then(setNovel).catch(() => undefined); }}
                  novel={novel} currentChapter={currentChapter} selectedText={selectedText}
                  selectionStart={selectionStart} selectionEnd={selectionEnd} plotDirectionHint={plotDirectionHint}
                  onPlotSelected={handlePlotSelected} onPlotSelectedAndContinue={handlePlotSelectedAndContinue} onError={setError} />}
              </Box>
            </Box>
          </Box>
        </Box>
        <Box component="footer" sx={{ minHeight: 28, flexShrink: 0, display: 'flex', alignItems: 'center', px: 1, gap: 1, borderTop: 1, borderColor: 'divider', bgcolor: 'background.paper' }}>
          <AutoSaver status={saveStatus} lastSavedAt={lastSavedAt} />
          <Box sx={{ flex: 1 }} />
          <IconButton size="small" aria-label="撤销" disabled={!canUndo || editorTab !== 'chapter'} onClick={handleUndo}><UndoIcon sx={{ fontSize: 16 }} /></IconButton>
          <IconButton size="small" aria-label="重做" disabled={!canRedo || editorTab !== 'chapter'} onClick={handleRedo}><RedoIcon sx={{ fontSize: 16 }} /></IconButton>
          <Typography variant="caption">本章 {countTextUnits(content).toLocaleString()} 字 · 全书 {novelTotalWords.toLocaleString()} 字</Typography>
        </Box>
      </Box>

      <Menu
        anchorEl={chapterMenuAnchor}
        open={Boolean(chapterMenuAnchor)}
        onClose={handleChapterMenuClose}
      >
        <MenuItem onClick={handleEditChapterOpen}>
          <EditIcon sx={{ mr: 1 }} fontSize="small" />
          编辑标题
        </MenuItem>
        <MenuItem onClick={handleDeleteChapterOpen} sx={{ color: 'error.main' }}>
          <DeleteIcon sx={{ mr: 1 }} fontSize="small" />
          删除章节
        </MenuItem>
      </Menu>

      <ChapterConflictDialog
        open={conflictDialogOpen}
        conflict={conflict}
        serverChapter={conflictServerChapter}
        loadingServer={conflictLoadingServer}
        actionLoading={conflictActionLoading}
        onAcceptServer={handleAcceptServerConflict}
        onOverwriteServer={() => void handleOverwriteServerConflict()}
        onCopyToNewChapter={() => void handleCopyToNewChapter()}
        onClose={() => setConflictDialogOpen(false)}
      />

      <Dialog open={createChapterDialogOpen} onClose={() => setCreateChapterDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>新建下一章</DialogTitle>
        <DialogContent>
          <Alert severity="info" sx={{ mt: 1, mb: 1 }}>
            章节序号由服务端自动分配，避免多人操作时产生重复编号。
          </Alert>
          <TextField
            fullWidth
            label="章节标题"
            value={newChapterTitle}
            onChange={(event) => setNewChapterTitle(event.target.value)}
            margin="normal"
            placeholder="可留空，将按服务端分配的章节号生成标题"
            autoFocus
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateChapterDialogOpen(false)}>取消</Button>
          <Button variant="contained" onClick={() => void handleCreateChapter()} disabled={creatingChapter}>
            {creatingChapter ? '创建中...' : '创建章节'}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={editChapterDialogOpen} onClose={() => setEditChapterDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>编辑章节标题</DialogTitle>
        <DialogContent>
          <TextField
            fullWidth
            label="章节标题"
            value={editChapterTitle}
            onChange={(event) => setEditChapterTitle(event.target.value)}
            margin="normal"
            autoFocus
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditChapterDialogOpen(false)}>取消</Button>
          <Button variant="contained" onClick={() => void handleUpdateChapter()} disabled={updatingChapter || !editChapterTitle.trim()}>
            {updatingChapter ? '更新中...' : '更新章节'}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={deleteChapterDialogOpen} onClose={() => setDeleteChapterDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <WarningIcon color="error" />
          确认删除章节
        </DialogTitle>
        <DialogContent>
          <Alert severity="error" sx={{ mb: 2 }}>
            此操作不可撤销。
          </Alert>
          {selectedChapterForMenu && (
            <Typography>
              第{selectedChapterForMenu.chapter_number}章 - {selectedChapterForMenu.title}
            </Typography>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteChapterDialogOpen(false)}>取消</Button>
          <Button variant="contained" color="error" onClick={() => void handleDeleteChapter()} disabled={deletingChapter}>
            {deletingChapter ? '删除中...' : '确认删除'}
          </Button>
        </DialogActions>
      </Dialog>
    </Fragment>
  );
}

function WorkspacePageContent() {
  const authenticatedUser = useAuthenticatedUser();
  if (!authenticatedUser) return <Box sx={{ p: 3 }}>
    <Typography role="status">正在核验登录身份。若会话已失效，请重新登录。</Typography>
    <Button href="/login">前往登录</Button>
  </Box>;
  // 作者改变时卸载正文、撤销历史及所有在途操作，重新读取该作者可访问的作品。
  return <WorkspaceSession key={authenticatedUser.id} authenticatedUser={authenticatedUser} />;
}

export default function WorkspacePage() {
  return (
    <Suspense
      fallback={
        <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100dvh' }}>
          <CircularProgress />
        </Box>
      }
    >
      <WorkspacePageContent />
    </Suspense>
  );
}
