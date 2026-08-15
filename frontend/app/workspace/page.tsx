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
  AppBar,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
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
  ListItemSecondaryAction,
  ListItemText,
  Menu,
  MenuItem,
  TextField,
  Toolbar,
  Typography,
  useMediaQuery,
  useTheme,
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
import { useWorkspaceKeyboardShortcuts } from '@/hooks/useWorkspaceKeyboardShortcuts';
import { countTextUnits } from '@/lib/textStats';
import { runAfterSave } from '@/lib/workspaceNavigation';
import type {
  AgentWorkflowTrace,
  Chapter,
  ChapterSummary,
  Novel,
} from '@/types';
import type { AiWritingAssistantRef } from '@/components/workspace/AiWritingAssistant';
import AiWritingAssistant from '@/components/workspace/AiWritingAssistant';
import AutoSaver from '@/components/workspace/AutoSaver';
import CharacterStats from '@/components/workspace/CharacterStats';
import ConsistencyChecker from '@/components/workspace/ConsistencyChecker';
import PlotOptionsGenerator from '@/components/workspace/PlotOptionsGenerator';
import ResearchAssistant from '@/components/workspace/ResearchAssistant';
import StyleManager from '@/components/workspace/StyleManager';
import TextRewriter from '@/components/workspace/TextRewriter';
import WorkflowPanel from '@/components/workspace/WorkflowPanel';

const DRAWER_WIDTH = 280;
const AI_PANEL_WIDTH = 400;
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
    <Box sx={{ p: 2, height: '100%', overflow: 'auto' }}>
      <Box sx={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <Typography variant="h6" gutterBottom fontWeight="600">
          章节管理
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
            <ListItem
              key={chapter.id}
              onClick={() => onSelect(chapter.id)}
              sx={{
                border: '1px solid',
                borderColor: currentChapterId === chapter.id ? 'primary.main' : 'divider',
                borderRadius: 1,
                mb: 1,
                cursor: 'pointer',
                contentVisibility: 'auto',
                containIntrinsicSize: '0 88px',
                '&:hover': {
                  borderColor: 'primary.main',
                  bgcolor: 'action.hover',
                },
              }}
            >
              <ListItemText
                disableTypography
                primary={
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Typography variant="body2" fontWeight="medium">
                      第{chapter.chapter_number}章
                    </Typography>
                    {currentChapterId === chapter.id && (
                      <Chip label="当前" size="small" color="primary" />
                    )}
                  </Box>
                }
                secondary={
                  <Box sx={{ mt: 0.5, pr: 3 }}>
                    <Typography variant="body2" noWrap sx={{ fontWeight: 500 }}>
                      {chapter.title}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {(chapter.word_count || 0).toLocaleString()} 字
                    </Typography>
                  </Box>
                }
              />
              <ListItemSecondaryAction>
                <IconButton
                  size="small"
                  aria-label={`管理第${chapter.chapter_number}章`}
                  onClick={(event) => {
                    event.stopPropagation();
                    onMenuOpen(event, chapter);
                  }}
                >
                  <MoreVertIcon />
                </IconButton>
              </ListItemSecondaryAction>
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

function WorkspacePageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const novelId = Number(searchParams.get('novel')) || 0;
  const requestedChapterId = Number(searchParams.get('chapter')) || 0;
  const theme = useTheme();
  const desktopAiPanel = useMediaQuery(theme.breakpoints.up('lg'));

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
  const [aiPanelOpen, setAiPanelOpen] = useState(false);

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

  const [selectionStart, setSelectionStart] = useState<number | null>(null);
  const [selectionEnd, setSelectionEnd] = useState<number | null>(null);
  const [selectedText, setSelectedText] = useState('');
  const contentInputRef = useRef<HTMLTextAreaElement | null>(null);
  const [selectedStyleSampleId, setSelectedStyleSampleId] = useState<number | null>(null);
  const [plotDirectionHint, setPlotDirectionHint] = useState<string | null>(null);
  const [workflowTrace, setWorkflowTrace] = useState<AgentWorkflowTrace | null>(null);
  const aiWritingAssistantRef = useRef<AiWritingAssistantRef | null>(null);

  const novelRequestRef = useRef<{ id: number; controller: AbortController } | null>(null);
  const workspaceRequestRef = useRef<{ id: number; controller: AbortController } | null>(null);
  const loadMoreRequestRef = useRef<{ id: number; controller: AbortController } | null>(null);
  const conflictFetchControllerRef = useRef<AbortController | null>(null);
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
        setConflictServerChapter(serverChapter);
        setConflictLoadingServer(false);
      })
      .catch((loadError) => {
        if (loadError instanceof Error && loadError.name === 'AbortError') return;
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
    saveNow,
    overwriteConflict,
    adoptServerChapter,
  } = useChapterSave({
    novelId,
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
  }, [clearHistory]);

  const handleAcceptServerConflict = useCallback(() => {
    if (!conflictServerChapter) return;
    setConflictActionLoading('accept');
    adoptServerChapter(conflictServerChapter);
    applyServerChapterLocally(conflictServerChapter);
    setConflictDialogOpen(false);
    setConflictActionLoading(null);
  }, [adoptServerChapter, applyServerChapterLocally, conflictServerChapter]);

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
    if (!conflict || !conflictServerChapter) return;
    setConflictActionLoading('copy');
    try {
      const sourceTitle = conflict.snapshot.title.trim() || '未命名章节';
      const newChapter = await api.createNextChapter(novelId, {
        title: `${sourceTitle}（冲突副本）`,
        content: conflict.snapshot.content,
      });
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
      setError(copyError instanceof Error ? copyError.message : '另存新章节失败');
    } finally {
      setConflictActionLoading(null);
    }
  }, [
    adoptServerChapter,
    applyServerChapterLocally,
    conflict,
    conflictServerChapter,
    novelId,
    router,
  ]);

  const handleChapterSelected = useCallback(async (nextChapterId: number) => {
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

  const handleApplyGeneratedToNextChapter = useCallback(async (generatedText: string) => {
    await runAfterCurrentSave(async () => {
      const newChapter = await api.createNextChapter(novelId, { content: generatedText });
      setChapters((previous) => mergeChapterSummaries(previous, [toChapterSummary(newChapter)]));
      setChapterTotal((total) => total + 1);
      router.push(`/workspace?novel=${novelId}&chapter=${newChapter.id}`);
    });
  }, [novelId, router, runAfterCurrentSave]);

  const handleTextRewritten = useCallback((newText: string, start: number, end: number) => {
    const newContent = content.slice(0, start) + newText + content.slice(end);
    setContent(newContent);
    addToHistory(newContent, { immediate: true });
    setSelectedText('');
    setSelectionStart(null);
    setSelectionEnd(null);
  }, [addToHistory, content]);

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

  const aiPanelContent = (
    <Box sx={{ p: 2, height: '100%', overflow: 'auto' }}>
      <WorkflowPanel workflowTrace={workflowTrace} />
      <AiWritingAssistant
        ref={aiWritingAssistantRef}
        novelId={novelId}
        chapterId={currentChapter?.id ?? null}
        currentContent={content}
        onContentGenerated={handleContentGenerated}
        onError={setError}
        onWorkflowTraceChange={setWorkflowTrace}
        plotDirectionHint={plotDirectionHint}
        onApplyToNextChapter={handleApplyGeneratedToNextChapter}
      />
      <TextRewriter
        novelId={novelId}
        chapterId={currentChapter?.id ?? null}
        selectedText={selectedText}
        selectionStart={selectionStart}
        selectionEnd={selectionEnd}
        onTextRewritten={handleTextRewritten}
        onError={setError}
      />
      <PlotOptionsGenerator
        novelId={novelId}
        chapterId={currentChapter?.id ?? null}
        currentContent={content}
        onPlotSelected={handlePlotSelected}
        onPlotSelectedAndContinue={handlePlotSelectedAndContinue}
        onError={setError}
      />
      <StyleManager
        novelId={novelId}
        selectedStyleSampleId={selectedStyleSampleId}
        onStyleSampleSelected={setSelectedStyleSampleId}
        onError={setError}
      />
      <ResearchAssistant novelId={novelId} onError={setError} />
      <CharacterStats novel={novel} currentContent={content} />
      <ConsistencyChecker
        novel={novel}
        currentChapter={currentChapter}
        content={content}
        onError={setError}
      />
      {novel && (
        <Card>
          <CardContent>
            <Typography variant="subtitle2" gutterBottom>
              小说信息
            </Typography>
            <Divider sx={{ my: 1 }} />
            <Typography variant="body2" sx={{ mb: 1 }}>
              类型：{novel.genre || '未设置'}
            </Typography>
            <Typography variant="body2" sx={{ mb: 1, fontSize: '0.85rem' }}>
              简介：{novel.description || '暂无'}
            </Typography>
            {novel.worldview && (
              <Typography variant="body2" sx={{ fontSize: '0.85rem' }}>
                世界观：{novel.worldview.slice(0, 100)}...
              </Typography>
            )}
          </CardContent>
        </Card>
      )}
    </Box>
  );

  return (
    <Fragment>
      <Drawer
        variant="temporary"
        anchor="left"
        open={mobileOpen}
        onClose={() => setMobileOpen(false)}
        sx={{
          display: { xs: 'block', md: 'none' },
          '& .MuiDrawer-paper': { width: DRAWER_WIDTH, boxSizing: 'border-box' },
        }}
      >
        {chapterNavigator}
      </Drawer>

      <Box sx={{ display: 'flex', height: '100dvh', width: '100%' }}>
        <Drawer
          variant="permanent"
          sx={{
            display: { xs: 'none', md: 'block' },
            width: DRAWER_WIDTH,
            flexShrink: 0,
            '& .MuiDrawer-paper': {
              width: DRAWER_WIDTH,
              boxSizing: 'border-box',
              position: 'relative',
            },
          }}
        >
          {chapterNavigator}
        </Drawer>

        <Box
          component="main"
          sx={{ flexGrow: 1, minWidth: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}
        >
          <AppBar position="static" sx={{ bgcolor: 'primary.main', boxShadow: 1 }}>
            <Toolbar sx={{ gap: 1 }}>
              <IconButton
                color="inherit"
                edge="start"
                aria-label="打开章节列表"
                onClick={() => setMobileOpen(true)}
                sx={{ display: { md: 'none' } }}
              >
                <MenuIcon />
              </IconButton>
              <IconButton color="inherit" aria-label="返回" onClick={() => void handleBack()}>
                <ArrowBackIcon />
              </IconButton>

              <Box sx={{ flexGrow: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 1 }}>
                <Typography variant="h6" noWrap sx={{ color: 'primary.contrastText', fontWeight: 600, fontSize: '1.1rem' }}>
                  {novel?.title || '写作工作台'}
                </Typography>
                {currentChapter && (
                  <Chip
                    label={`第${currentChapter.chapter_number}章`}
                    size="small"
                    sx={{ display: { xs: 'none', sm: 'inline-flex' }, bgcolor: 'rgba(255,255,255,0.2)', color: 'primary.contrastText' }}
                  />
                )}
              </Box>

              <AutoSaver status={saveStatus} lastSavedAt={lastSavedAt} />
              <Button
                color="inherit"
                startIcon={<SaveIcon />}
                aria-label={isSaving ? '保存中' : '保存章节'}
                onClick={() => void handleSave()}
                disabled={isSaving || !isDirty}
                sx={{ minWidth: { xs: 40, sm: 80 }, px: { xs: 1, sm: 2 } }}
              >
                <Box component="span" sx={{ display: { xs: 'none', sm: 'inline' } }}>
                  {isSaving ? '保存中...' : '保存'}
                </Box>
              </Button>
              <ColorModeToggle inheritColor />
              <IconButton
                color="inherit"
                aria-label="打开 AI 助手"
                onClick={() => setAiPanelOpen(true)}
                sx={{ display: { lg: 'none' } }}
              >
                <SmartToyIcon />
              </IconButton>
            </Toolbar>
          </AppBar>

          <Box sx={{ flexGrow: 1, overflow: 'auto' }}>
            <Box sx={{ width: '100%', maxWidth: 900, minHeight: '100%', mx: 'auto', p: { xs: 2, sm: 4, md: 5 } }}>
              {error && (
                <Alert severity="error" onClose={() => setError('')} sx={{ mb: 2 }}>
                  {error}
                </Alert>
              )}

              {isOffline && isDirty && (
                <Alert severity="warning" sx={{ mb: 2 }}>
                  当前处于离线状态，{hasLocalBackup ? '草稿已保留在本机' : '正在保存本地草稿'}
                  ，恢复连接后会自动重试保存。
                </Alert>
              )}

              {loading ? (
                <Box sx={{ display: 'flex', justifyContent: 'center', mt: 4 }}>
                  <CircularProgress />
                </Box>
              ) : currentChapter ? (
                <>
                  <TextField
                    fullWidth
                    label="章节标题"
                    value={title}
                    onChange={(event) => setTitle(event.target.value)}
                    sx={{ mb: 4, '& .MuiInputBase-root': { fontSize: '1.5rem', fontWeight: 500 } }}
                  />
                  <TextField
                    fullWidth
                    multiline
                    minRows={18}
                    label="章节内容"
                    value={content}
                    onChange={(event) => {
                      const nextContent = event.target.value;
                      setContent(nextContent);
                      addToHistory(nextContent);
                    }}
                    onSelect={(event) => {
                      const target = event.target as HTMLTextAreaElement;
                      if (target.selectionStart !== target.selectionEnd) {
                        setSelectionStart(target.selectionStart);
                        setSelectionEnd(target.selectionEnd);
                        setSelectedText(target.value.slice(target.selectionStart, target.selectionEnd));
                      } else {
                        setSelectionStart(null);
                        setSelectionEnd(null);
                        setSelectedText('');
                      }
                    }}
                    inputRef={contentInputRef}
                    placeholder="开始写作..."
                    sx={{
                      '& .MuiInputBase-input': {
                        fontSize: '1rem',
                        lineHeight: 1.75,
                        letterSpacing: '0.02em',
                      },
                    }}
                  />

                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mt: 3, p: 2, bgcolor: 'background.subtle', borderRadius: 2, border: '1px solid', borderColor: 'border.light' }}>
                    <Box>
                      <IconButton size="small" aria-label="撤销" disabled={!canUndo} onClick={handleUndo}>
                        <UndoIcon fontSize="small" />
                      </IconButton>
                      <IconButton size="small" aria-label="重做" disabled={!canRedo} onClick={handleRedo}>
                        <RedoIcon fontSize="small" />
                      </IconButton>
                    </Box>
                    <Box sx={{ display: 'flex', gap: 1 }}>
                      <Chip
                        label={`本章 ${countTextUnits(content).toLocaleString()} 字`}
                        size="small"
                        variant="outlined"
                      />
                      <Chip
                        label={`全书 ${novelTotalWords.toLocaleString()} 字`}
                        size="small"
                        variant="outlined"
                      />
                    </Box>
                  </Box>
                </>
              ) : (
                <Box sx={{ textAlign: 'center', mt: 8 }}>
                  <Typography variant="h6" color="text.secondary" sx={{ mb: 1 }}>
                    请从章节列表选择一个章节开始编辑
                  </Typography>
                  <Button startIcon={<AddIcon />} onClick={handleCreateChapterOpen}>
                    新建下一章
                  </Button>
                </Box>
              )}
            </Box>
          </Box>
        </Box>

        <Drawer
          variant={desktopAiPanel ? 'permanent' : 'temporary'}
          anchor="right"
          open={desktopAiPanel || aiPanelOpen}
          onClose={() => setAiPanelOpen(false)}
          sx={{
            width: desktopAiPanel ? AI_PANEL_WIDTH : 0,
            flexShrink: 0,
            '& .MuiDrawer-paper': {
              width: { xs: 'min(92vw, 400px)', sm: AI_PANEL_WIDTH },
              boxSizing: 'border-box',
              position: desktopAiPanel ? 'relative' : 'fixed',
              height: '100%',
            },
          }}
        >
          {aiPanelContent}
        </Drawer>
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
