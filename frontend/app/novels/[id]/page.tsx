'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter, useParams } from 'next/navigation';
import {
  Box,
  Typography,
  Button,
  Card,
  CardContent,
  List,
  ListItem,
  IconButton,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Alert,
  Chip,
  Divider,
  LinearProgress,
  Grid,
  Accordion,
  AccordionSummary,
  AccordionDetails,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh';
import PsychologyIcon from '@mui/icons-material/Psychology';
import CreateIcon from '@mui/icons-material/Create';
import AppFrame from '@/components/layout/AppFrame';
import { countTextUnits } from '@/lib/textStats';
import { api } from '@/lib/api';
import type {
  ChapterNextCreate,
  ChapterSummary,
  Novel,
  NovelStatistics,
} from '@/types';

const CHAPTER_PAGE_SIZE = 50;

export default function NovelDetailPage() {
  const router = useRouter();
  const params = useParams();
  const novelId = Number(params.id);

  const [novel, setNovel] = useState<Novel | null>(null);
  const [chapters, setChapters] = useState<ChapterSummary[]>([]);
  const [chapterPage, setChapterPage] = useState(1);
  const [chapterTotal, setChapterTotal] = useState(0);
  const [hasMoreChapters, setHasMoreChapters] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [lastChapter, setLastChapter] = useState<ChapterSummary | null>(null);
  const [statistics, setStatistics] = useState<NovelStatistics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const loadRequestRef = useRef<{ id: number; controller: AbortController } | null>(null);
  const loadMoreRequestRef = useRef<{ id: number; controller: AbortController } | null>(null);
  const requestIdRef = useRef(0);

  // 创建章节对话框
  const [openDialog, setOpenDialog] = useState(false);
  const [chapterForm, setChapterForm] = useState<ChapterNextCreate>({
    title: '',
    content: '',
  });

  // AI生成状态
  const [aiGenerating, setAiGenerating] = useState(false);
  const [exporting, setExporting] = useState(false);

  // AI初始化设定状态
  const [initDialogOpen, setInitDialogOpen] = useState(false);
  const [initLoading, setInitLoading] = useState(false);
  const [initTheme, setInitTheme] = useState('');
  const [initTargetChapters, setInitTargetChapters] = useState(10);
  const [initWorldview, setInitWorldview] = useState('');
  const [initMainCharacters, setInitMainCharacters] = useState('');
  const [initOutline, setInitOutline] = useState('');
  const [initPlotHooks, setInitPlotHooks] = useState('');

  useEffect(() => {
    if (!openDialog) return;
    if (typeof window === 'undefined') return;

    try {
      const draftKey = `chapter_form_draft_new_${novelId}`;
      const draft = window.localStorage.getItem(draftKey);
      if (draft) {
        const parsed = JSON.parse(draft) as ChapterNextCreate;
        setChapterForm(parsed);
      }
    } catch {
      // 忽略草稿恢复错误
    }
  }, [openDialog, novelId]);

  useEffect(() => {
    if (!openDialog) return;
    if (typeof window === 'undefined') return;

    try {
      const draftKey = `chapter_form_draft_new_${novelId}`;
      window.localStorage.setItem(draftKey, JSON.stringify(chapterForm));
    } catch {
      // 忽略草稿写入错误
    }
  }, [openDialog, novelId, chapterForm]);

  const loadNovelAndChapters = useCallback(async () => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    loadRequestRef.current?.controller.abort();
    loadMoreRequestRef.current?.controller.abort();
    loadMoreRequestRef.current = null;
    setLoadingMore(false);
    const controller = new AbortController();
    loadRequestRef.current = { id: requestId, controller };
    setLoading(true);
    try {
      const [novelData, firstPage, allStatistics] = await Promise.all([
        api.getNovel(novelId, { signal: controller.signal }),
        api.getChapterSummaries(
          novelId,
          { page: 1, pageSize: CHAPTER_PAGE_SIZE },
          { signal: controller.signal },
        ),
        api.getNovelStatistics({ signal: controller.signal }).catch(() => []),
      ]);
      const lastPageNumber = Math.max(1, Math.ceil(firstPage.total / firstPage.page_size));
      const lastPage = lastPageNumber > 1
        ? await api.getChapterSummaries(
            novelId,
            { page: lastPageNumber, pageSize: firstPage.page_size },
            { signal: controller.signal },
          )
        : firstPage;

      if (loadRequestRef.current?.id !== requestId) return;
      setNovel(novelData);
      setChapters(firstPage.items);
      setChapterPage(firstPage.page);
      setChapterTotal(firstPage.total);
      setHasMoreChapters(firstPage.has_more);
      setLastChapter(lastPage.items.at(-1) ?? null);
      setStatistics(allStatistics.find((item) => item.novel_id === novelId) ?? null);
      setError('');
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') return;
      if (loadRequestRef.current?.id !== requestId) return;
      setError(err instanceof Error ? err.message : '加载失败');
      setTimeout(() => router.push('/dashboard'), 2000);
    } finally {
      if (loadRequestRef.current?.id === requestId) setLoading(false);
    }
  }, [novelId, router]);

  useEffect(() => {
    void loadNovelAndChapters();
    return () => {
      loadRequestRef.current?.controller.abort();
      loadMoreRequestRef.current?.controller.abort();
    };
  }, [loadNovelAndChapters]);

  const handleExport = async () => {
    if (!novel || exporting) return;
    setExporting(true);
    setError('');
    try {
      const blob = await api.exportNovelText(novelId);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${novel.title.replace(/[\\/:*?"<>|]/g, '_') || '小说'}.txt`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '导出失败，请重试');
    } finally { setExporting(false); }
  };

  const handleCreateChapter = () => {
    setChapterForm({
      title: '',
      content: '',
    });
    setOpenDialog(true);
  };

  const handleAutoCreateChapter = async () => {
    try {
      setAiGenerating(true);

      const newChapter = await api.autoCreateChapter({
        novel_id: novelId,
        base_chapter_id: lastChapter?.id,
        target_length: 500,
      });

      await loadNovelAndChapters();
      router.push(`/workspace?novel=${novelId}&chapter=${newChapter.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'AI自动生成章节失败');
    } finally {
      setAiGenerating(false);
    }
  };

  const handleSaveChapter = async () => {
    try {
      const newChapter = await api.createNextChapter(novelId, {
        title: chapterForm.title?.trim() || undefined,
        content: chapterForm.content,
      });

      if (typeof window !== 'undefined') {
        const draftKey = `chapter_form_draft_new_${novelId}`;
        window.localStorage.removeItem(draftKey);
      }

      setOpenDialog(false);
      await loadNovelAndChapters();
      router.push(`/workspace?novel=${novelId}&chapter=${newChapter.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    }
  };

  const handleLoadMore = useCallback(async () => {
    if (loadingMore || !hasMoreChapters) return;
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    loadMoreRequestRef.current?.controller.abort();
    const controller = new AbortController();
    loadMoreRequestRef.current = { id: requestId, controller };
    setLoadingMore(true);
    try {
      const nextPage = chapterPage + 1;
      const result = await api.getChapterSummaries(
        novelId,
        { page: nextPage, pageSize: CHAPTER_PAGE_SIZE },
        { signal: controller.signal },
      );
      if (loadMoreRequestRef.current?.id !== requestId) return;
      setChapters((previous) => {
        const byId = new Map(previous.map((chapter) => [chapter.id, chapter]));
        for (const chapter of result.items) byId.set(chapter.id, chapter);
        return Array.from(byId.values()).sort(
          (left, right) => left.chapter_number - right.chapter_number,
        );
      });
      setChapterPage(result.page);
      setChapterTotal(result.total);
      setHasMoreChapters(result.has_more);
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') return;
      if (loadMoreRequestRef.current?.id !== requestId) return;
      setError(err instanceof Error ? err.message : '加载更多章节失败');
    } finally {
      if (loadMoreRequestRef.current?.id === requestId) {
        loadMoreRequestRef.current = null;
        setLoadingMore(false);
      }
    }
  }, [chapterPage, hasMoreChapters, loadingMore, novelId]);

  const maxChapterWords = useMemo(
    () => Math.max(...chapters.map((chapter) => chapter.word_count || 0), 1),
    [chapters],
  );

  const handleGenerateInit = async () => {
    try {
      setInitLoading(true);
      const result = await api.initNovel({
        novel_id: novelId,
        target_chapters: initTargetChapters,
        theme: initTheme || undefined,
      });

      setInitWorldview(result.worldview || '');
      setInitMainCharacters(
        result.main_characters && result.main_characters.length > 0
          ? result.main_characters.join('\n')
          : '',
      );
      setInitOutline(result.outline || '');
      setInitPlotHooks(
        result.plot_hooks && result.plot_hooks.length > 0
          ? result.plot_hooks.join('\n')
          : '',
      );
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : '初始化设定失败');
    } finally {
      setInitLoading(false);
    }
  };

  const handleApplyInit = async () => {
    if (!novel) return;

    const combinedWorldview = `【世界观】\n${initWorldview}\n\n【主要角色】\n${initMainCharacters}\n\n【章节大纲】\n${initOutline}\n\n【剧情线索】\n${initPlotHooks}`;

    try {
      const updated = await api.updateNovel(novelId, {
        worldview: combinedWorldview,
      });
      setNovel(updated);
      setInitDialogOpen(false);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : '应用设定失败');
    }
  };

  const handleDeleteChapter = async (chapterId: number) => {
    if (!confirm('确定要删除这个章节吗？')) return;

    try {
      await api.deleteChapter(novelId, chapterId);
      await loadNovelAndChapters();
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败');
    }
  };

  const displayChapterCount = statistics?.chapter_count ?? chapterTotal;
  const displayTotalWords = statistics?.total_words ?? chapters.reduce(
    (sum, chapter) => sum + (chapter.word_count || 0),
    0,
  );

  if (loading) {
    return (
      <AppFrame eyebrow="项目" title="正在打开项目…" backHref="/dashboard" backLabel="返回项目列表">
        <Box sx={{ py: 4, textAlign: 'center' }}><LinearProgress /></Box>
      </AppFrame>
    );
  }

  if (!novel) {
    return null;
  }

  return (
    <AppFrame
      eyebrow="项目"
      title={novel.title}
      description={novel.description || '在这里管理章节、设定与整本导出；写作本身在工作台完成。'}
      backHref="/dashboard"
      backLabel="返回项目列表"
      actions={lastChapter ? (
        <Button
          size="small"
          variant="contained"
          onClick={() => router.push(`/workspace?novel=${novelId}&chapter=${lastChapter.id}`)}
        >
          继续写第 {lastChapter.chapter_number} 章
        </Button>
      ) : (
        <Button size="small" variant="contained" onClick={handleCreateChapter}>
          创建第 1 章
        </Button>
      )}
    >
      <Box>
        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>
            {error}
          </Alert>
        )}

        {/* 进度统计卡片 */}
        <Grid container spacing={2} sx={{ mb: 3 }}>
          <Grid item xs={12} sm={4}>
            <Card>
              <CardContent>
                <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                  总字数
                </Typography>
                <Typography variant="h4">
                  {displayTotalWords.toLocaleString()}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} sm={4}>
            <Card>
              <CardContent>
                <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                  章节数
                </Typography>
                <Typography variant="h4">
                  {displayChapterCount}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} sm={4}>
            <Card>
              <CardContent>
                <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                  平均字数/章
                </Typography>
                <Typography variant="h4">
                  {displayChapterCount > 0
                    ? Math.round(displayTotalWords / displayChapterCount).toLocaleString()
                    : 0}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        </Grid>

        {/* 小说信息卡片 */}
        <Card sx={{ mb: 3 }}>
          <CardContent>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 2 }}>
              <Box>
                <Typography variant="h4" gutterBottom>
                  {novel.title}
                </Typography>
                <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                  {novel.genre && (
                    <Chip label={novel.genre} size="small" color="primary" />
                  )}
                  <Chip
                    label={`${displayChapterCount} 章节`}
                    size="small"
                    variant="outlined"
                  />
                </Box>
              </Box>
              <Box>
                <Button
                  variant="outlined"
                  size="small"
                  startIcon={<PsychologyIcon />}
                  onClick={() => setInitDialogOpen(true)}
                >
                  AI初始化设定
                </Button>
                <Button size="small" onClick={() => router.push(`/novels/${novelId}/story-bible`)}>管理设定与伏笔</Button>
                <Button size="small" disabled={exporting} onClick={() => void handleExport()}>{exporting ? '导出中…' : '导出全书 TXT'}</Button>
              </Box>
            </Box>

            <Box sx={{ mt: 2 }}>
              {!lastChapter ? (
                <Button
                  variant="contained"
                  size="small"
                  onClick={handleCreateChapter}
                >
                  创建第 1 章并开始写作
                </Button>
              ) : (
                <Button
                  variant="contained"
                  size="small"
                  onClick={() => {
                    router.push(`/workspace?novel=${novelId}&chapter=${lastChapter.id}`);
                  }}
                >
                  继续写第 {lastChapter.chapter_number} 章
                </Button>
              )}
            </Box>

            {novel.description && (
              <>
                <Divider sx={{ my: 2 }} />
                <Typography variant="subtitle2" color="text.secondary">
                  简介
                </Typography>
                <Typography variant="body1" sx={{ mt: 1 }}>
                  {novel.description}
                </Typography>
              </>
            )}

            {novel.worldview && (
              <>
                <Divider sx={{ my: 2 }} />
                <Typography variant="subtitle2" color="text.secondary">
                  世界观设定
                </Typography>
                <Typography variant="body1" sx={{ mt: 1 }}>
                  {novel.worldview}
                </Typography>
              </>
            )}
          </CardContent>
        </Card>

        {/* 章节列表 */}
        <Card>
          <CardContent>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
              <Typography variant="h6">章节列表</Typography>
              <Box>
                <Button
                  variant="outlined"
                  size="small"
                  startIcon={<AutoFixHighIcon />}
                  onClick={handleAutoCreateChapter}
                  disabled={aiGenerating}
                  sx={{ mr: 1 }}
                >
                  AI 新章节
                </Button>
                <Button
                  variant="contained"
                  size="small"
                  startIcon={<AddIcon />}
                  onClick={handleCreateChapter}
                >
                  新建章节
                </Button>
              </Box>
            </Box>

            {chapters.length === 0 ? (
              <Box sx={{ textAlign: 'center', py: 4 }}>
                <Typography variant="body2" color="text.secondary">
                  还没有创建任何章节
                </Typography>
              </Box>
            ) : (
              <List>
                {chapters.map((chapter, index) => {
                  const progress = ((chapter.word_count || 0) / maxChapterWords) * 100;
                  return (
                    <ListItem
                      key={chapter.id}
                      divider={index < chapters.length - 1}
                      sx={{
                        flexDirection: 'column',
                        alignItems: 'stretch',
                        py: 2,
                        '&:hover': {
                          bgcolor: 'action.hover',
                        },
                      }}
                    >
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%', mb: 1 }}>
                        <Box sx={{ flex: 1, minWidth: 0, mr: 2 }}>
                          <Typography variant="body1" sx={{ fontWeight: 500 }}>
                            第 {chapter.chapter_number} 章：{chapter.title}
                          </Typography>
                          <Box sx={{ display: 'flex', gap: 1, mt: 0.5 }}>
                            <Chip
                              label={`${chapter.word_count || 0} 字`}
                              size="small"
                              variant="outlined"
                            />
                          </Box>
                        </Box>
                        <Box sx={{ display: 'flex', gap: 1 }}>
                          <IconButton
                            size="small"
                            onClick={() => router.push(`/workspace?novel=${novelId}&chapter=${chapter.id}`)}
                            title="进入写作工作台"
                            color="primary"
                          >
                            <CreateIcon />
                          </IconButton>
                          <IconButton
                            size="small"
                            onClick={() => handleDeleteChapter(chapter.id)}
                            color="error"
                          >
                            <DeleteIcon />
                          </IconButton>
                        </Box>
                      </Box>
                      <LinearProgress
                        variant="determinate"
                        value={progress}
                        sx={{
                          height: 6,
                          borderRadius: 3,
                          bgcolor: 'action.hover',
                          '& .MuiLinearProgress-bar': {
                            bgcolor: 'primary.main',
                          },
                        }}
                      />
                    </ListItem>
                  );
                })}
              </List>
            )}
            {hasMoreChapters && (
              <Button
                fullWidth
                onClick={() => void handleLoadMore()}
                disabled={loadingMore}
                sx={{ mt: 2 }}
              >
                {loadingMore ? '加载中...' : `加载更多（已加载 ${chapters.length}/${chapterTotal}）`}
              </Button>
            )}
          </CardContent>
        </Card>
      </Box>

      {/* 创建章节对话框 */}
      <Dialog
        open={openDialog}
        onClose={() => setOpenDialog(false)}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>新建章节</DialogTitle>
        <DialogContent>
          <Alert severity="info" sx={{ mt: 1 }}>
            章节就像项目里的一个文件：先建出来，正文稍后在写作台里写，或直接让 AI 续写。
          </Alert>
          <TextField
            fullWidth
            label="章节标题（可留空）"
            value={chapterForm.title ?? ''}
            onChange={(e) => setChapterForm({ ...chapterForm, title: e.target.value })}
            margin="normal"
            autoFocus
            placeholder="留空则自动命名为第 N 章"
          />
          <Accordion elevation={0} sx={{ mt: 2, border: 1, borderColor: 'divider', '&:before': { display: 'none' } }}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="body2">想先粘贴一段草稿？（可选）</Typography>
            </AccordionSummary>
            <AccordionDetails>
              <TextField
                fullWidth
                label="章节正文（可留空）"
                value={chapterForm.content ?? ''}
                onChange={(e) => setChapterForm({ ...chapterForm, content: e.target.value })}
                multiline
                rows={10}
                helperText={`当前字数：${countTextUnits(chapterForm.content || '')}`}
              />
            </AccordionDetails>
          </Accordion>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpenDialog(false)}>取消</Button>
          <Button onClick={handleSaveChapter} variant="contained">
            创建并开始写作
          </Button>
        </DialogActions>
      </Dialog>

      {/* AI初始化小说设定对话框 */}
      <Dialog
        open={initDialogOpen}
        onClose={() => setInitDialogOpen(false)}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>AI初始化小说设定</DialogTitle>
        <DialogContent>
          <TextField
            fullWidth
            label="故事主题/补充说明"
            value={initTheme}
            onChange={(e) => setInitTheme(e.target.value)}
            margin="normal"
          />
          <TextField
            fullWidth
            type="number"
            label="目标章节数"
            value={initTargetChapters}
            onChange={(e) => setInitTargetChapters(Number(e.target.value) || 1)}
            margin="normal"
            inputProps={{ min: 1 }}
          />
          <Box sx={{ my: 2 }}>
            <Button
              variant="contained"
              onClick={handleGenerateInit}
              disabled={initLoading}
            >
              {initLoading ? '生成中...' : '生成AI设定'}
            </Button>
          </Box>
          <TextField
            fullWidth
            label="世界观设定"
            value={initWorldview}
            onChange={(e) => setInitWorldview(e.target.value)}
            margin="normal"
            multiline
            rows={4}
          />
          <TextField
            fullWidth
            label="主要角色（每行一个）"
            value={initMainCharacters}
            onChange={(e) => setInitMainCharacters(e.target.value)}
            margin="normal"
            multiline
            rows={4}
          />
          <TextField
            fullWidth
            label="故事大纲"
            value={initOutline}
            onChange={(e) => setInitOutline(e.target.value)}
            margin="normal"
            multiline
            rows={4}
          />
          <TextField
            fullWidth
            label="剧情线索（每行一个）"
            value={initPlotHooks}
            onChange={(e) => setInitPlotHooks(e.target.value)}
            margin="normal"
            multiline
            rows={4}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setInitDialogOpen(false)}>取消</Button>
          <Button
            onClick={handleApplyInit}
            variant="contained"
            disabled={
              !initWorldview && !initMainCharacters && !initOutline && !initPlotHooks
            }
          >
            应用到小说
          </Button>
        </DialogActions>
      </Dialog>
    </AppFrame>
  );
}
