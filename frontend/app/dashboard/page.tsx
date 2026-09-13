'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Box,
  Typography,
  Button,
  Grid,
  Card,
  CardContent,
  CardActions,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Alert,
  LinearProgress,
  Chip,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Stack,
} from '@mui/material';
import InputAdornment from '@mui/material/InputAdornment';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';
import MenuBookIcon from '@mui/icons-material/MenuBook';
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh';
import SearchIcon from '@mui/icons-material/Search';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import AppFrame from '@/components/layout/AppFrame';
import { countTextUnits } from '@/lib/textStats';
import { api, ApiError } from '@/lib/api';
import type { Novel, NovelCreate } from '@/types';

export default function DashboardPage() {
  const router = useRouter();
  const [novels, setNovels] = useState<Novel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [openDialog, setOpenDialog] = useState(false);
  const [editingNovel, setEditingNovel] = useState<Novel | null>(null);
  const [novelForm, setNovelForm] = useState<NovelCreate>({
    title: '',
    genre: '',
    description: '',
    worldview: '',
  });
  const [quickTitle, setQuickTitle] = useState('');
  const [quickCreating, setQuickCreating] = useState(false);
  const [lastWorkspace, setLastWorkspace] = useState<{ novelId: number; chapterId: number } | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [autoCreatingNovelId, setAutoCreatingNovelId] = useState<number | null>(null);
  const [generatedChapter, setGeneratedChapter] = useState<any | null>(null);
  const [showChapterPreview, setShowChapterPreview] = useState(false);
  const [generationStep, setGenerationStep] = useState('');
  const [novelStats, setNovelStats] = useState<Record<number, { chapterCount: number; totalWords: number }>>({});
  const [statsLoading, setStatsLoading] = useState(false);
  const [statsError, setStatsError] = useState('');
  const loadRequestRef = useRef<{ id: number; controller: AbortController } | null>(null);

  useEffect(() => {
    if (typeof window === 'undefined') return;

    try {
      const raw = window.localStorage.getItem('last_workspace');
      if (!raw) return;
      const parsed = JSON.parse(raw) as { novelId: number; chapterId: number };
      if (parsed.novelId && parsed.chapterId) {
        setLastWorkspace(parsed);
      }
    } catch {
      // 忽略本地记录解析错误
    }
  }, []);

  useEffect(() => {
    if (!openDialog) return;
    if (typeof window === 'undefined') return;

    try {
      if (editingNovel) {
        const draftKey = `novel_form_draft_edit_${editingNovel.id}`;
        const draft = window.localStorage.getItem(draftKey);
        if (draft) {
          const parsed = JSON.parse(draft) as NovelCreate;
          setNovelForm(parsed);
        }
      } else {
        const draftKey = 'novel_form_draft_new';
        const draft = window.localStorage.getItem(draftKey);
        if (draft) {
          const parsed = JSON.parse(draft) as NovelCreate;
          setNovelForm(parsed);
        }
      }
    } catch {
      // 忽略草稿恢复错误
    }
  }, [openDialog, editingNovel]);

  useEffect(() => {
    if (!openDialog) return;
    if (typeof window === 'undefined') return;

    try {
      const draftKey = editingNovel
        ? `novel_form_draft_edit_${editingNovel.id}`
        : 'novel_form_draft_new';
      window.localStorage.setItem(draftKey, JSON.stringify(novelForm));
    } catch {
      // 忽略草稿写入错误
    }
  }, [openDialog, editingNovel, novelForm]);

  const loadNovels = useCallback(async () => {
    const requestId = (loadRequestRef.current?.id ?? 0) + 1;
    loadRequestRef.current?.controller.abort();
    const controller = new AbortController();
    loadRequestRef.current = { id: requestId, controller };

    setLoading(true);
    setStatsLoading(true);
    void api
      .getNovelStatistics({ signal: controller.signal })
      .then((statistics) => {
        if (loadRequestRef.current?.id !== requestId) return;
        const statsMap: Record<number, { chapterCount: number; totalWords: number }> = {};
        for (const item of statistics) {
          statsMap[item.novel_id] = {
            chapterCount: item.chapter_count,
            totalWords: item.total_words,
          };
        }
        setNovelStats(statsMap);
        setStatsError('');
      })
      .catch((err) => {
        if (err instanceof Error && err.name === 'AbortError') return;
        if (loadRequestRef.current?.id !== requestId) return;
        setNovelStats({});
        setStatsError('统计数据暂不可用，小说列表和编辑功能不受影响');
      })
      .finally(() => {
        if (loadRequestRef.current?.id === requestId) setStatsLoading(false);
      });

    try {
      const data = await api.getNovels();
      if (loadRequestRef.current?.id !== requestId) return;
      setNovels(data);
      setError('');
    } catch (err) {
      if (loadRequestRef.current?.id !== requestId) return;
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        setError('登录状态已失效，请重新登录');
        setTimeout(() => router.push('/'), 2000);
      } else {
        setError(err instanceof Error ? err.message : '获取小说列表失败');
      }
    } finally {
      if (loadRequestRef.current?.id === requestId) setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    void loadNovels();
    return () => loadRequestRef.current?.controller.abort();
  }, [loadNovels]);

  /** 创建只需要一个名字；其余信息进工作台后再补。 */
  const createFromName = async () => {
    const title = quickTitle.trim();
    if (!title || quickCreating) return;
    setQuickCreating(true);
    setError('');
    try {
      const created = await api.createNovel({ title });
      setQuickTitle('');
      await loadNovels();
      router.push(`/workspace?novel=${created.id}`);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '创建失败，请重试');
    } finally {
      setQuickCreating(false);
    }
  };

  const handleEditNovel = (novel: Novel) => {
    setNovelForm({
      title: novel.title,
      genre: novel.genre || '',
      description: novel.description || '',
      worldview: novel.worldview || '',
    });
    setEditingNovel(novel);
    setOpenDialog(true);
  };

  const handleSaveNovel = async () => {
    const title = novelForm.title.trim();
    if (!title) return;
    try {
      if (editingNovel) {
        await api.updateNovel(editingNovel.id, novelForm);
      } else {
        const created = await api.createNovel({ ...novelForm, title });
        setOpenDialog(false);
        if (typeof window !== 'undefined') window.localStorage.removeItem('novel_form_draft_new');
        await loadNovels();
        router.push(`/workspace?novel=${created.id}`);
        return;
      }
      setOpenDialog(false);
      if (typeof window !== 'undefined') {
        window.localStorage.removeItem(`novel_form_draft_edit_${editingNovel.id}`);
      }
      await loadNovels();
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    }
  };

  const handleDeleteNovel = async (novelId: number) => {
    if (!confirm('确定要删除这部小说吗？删除后将无法恢复，所有章节也会被删除。')) return;

    try {
      await api.deleteNovel(novelId);
      await loadNovels();
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败');
    }
  };

  const handleAutoCreateNextChapter = async (novelId: number) => {
    try {
      setAutoCreatingNovelId(novelId);
      setGenerationStep('正在生成章节标题和内容...');

      const newChapter = await api.autoCreateChapter({
        novel_id: novelId,
      });

      setGenerationStep('');
      setGeneratedChapter({ ...newChapter, novelId });
      setShowChapterPreview(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'AI自动生成章节失败');
      setGenerationStep('');
    } finally {
      setAutoCreatingNovelId(null);
    }
  };

  const handleGoToEdit = () => {
    if (!generatedChapter) return;
    setShowChapterPreview(false);
    router.push(`/workspace?novel=${generatedChapter.novelId}&chapter=${generatedChapter.id}`);
  };

  const handleStayInDashboard = () => {
    setShowChapterPreview(false);
    setGeneratedChapter(null);
    loadNovels();
  };

  const filteredNovels = novels.filter((novel) => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return true;
    return (
      novel.title.toLowerCase().includes(query) ||
      (novel.genre || '').toLowerCase().includes(query) ||
      (novel.description || '').toLowerCase().includes(query)
    );
  });

  const handleLogout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    router.push('/');
  };

  const totalNovels = novels.length;
  const totalChapters = Object.values(novelStats).reduce((sum, s) => sum + s.chapterCount, 0);
  const totalWords = Object.values(novelStats).reduce((sum, s) => sum + s.totalWords, 0);

  if (loading) {
    return (
      <AppFrame eyebrow="项目" title="正在载入你的项目…">
        <Box sx={{ py: 4 }}><LinearProgress /></Box>
      </AppFrame>
    );
  }

  return (
    <AppFrame
      eyebrow="项目"
      title="你的小说项目"
      description="每部小说就是一个项目：先创建，再在工作台里逐章写作。"
      actions={
        <>
          {lastWorkspace && (
            <Button
              size="small"
              onClick={() => router.push(`/workspace?novel=${lastWorkspace.novelId}&chapter=${lastWorkspace.chapterId}`)}
            >
              继续上次写作
            </Button>
          )}
          <Button size="small" onClick={handleLogout}>退出登录</Button>
        </>
      }
    >
      <Box>
        <Card sx={{ mb: 3 }}>
          <CardContent>
            <Typography variant="h6" gutterBottom sx={{ fontWeight: 700 }}>
              新建小说
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              起个名字就能开始。类型、简介、世界观、角色和大纲都进工作台后再说——你可以自己写，也可以让 AI 起草。
            </Typography>
            <Stack direction={{ xs: 'column', sm: 'row' }} gap={1}>
              <TextField
                fullWidth
                size="small"
                label="小说名称"
                value={quickTitle}
                disabled={quickCreating}
                onChange={(event) => setQuickTitle(event.target.value)}
                onKeyDown={(event) => { if (event.key === 'Enter' && !event.nativeEvent.isComposing) void createFromName(); }}
                placeholder="例如：长河行"
              />
              <Button
                variant="contained"
                disabled={quickCreating || !quickTitle.trim()}
                onClick={() => void createFromName()}
                sx={{ flexShrink: 0, minWidth: 180 }}
              >
                {quickCreating ? '正在创建…' : '创建并开始写作'}
              </Button>
            </Stack>
          </CardContent>
        </Card>

        <Box sx={{ mb: 3 }}>
          <Card>
            <CardContent>
              <Typography variant="subtitle1" gutterBottom>
                写作数据总览
              </Typography>
              <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
                <Box>
                  <Typography variant="h4">{totalNovels}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    小说数量
                  </Typography>
                </Box>
                <Box>
                  <Typography variant="h4">{statsLoading ? '...' : totalChapters}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    总章节数
                  </Typography>
                </Box>
                <Box>
                  <Typography variant="h4">{statsLoading ? '...' : totalWords}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    总字数
                  </Typography>
                </Box>
              </Box>
            </CardContent>
          </Card>
        </Box>

        <Typography variant="h5" sx={{ mb: 2 }}>全部项目</Typography>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>
            {error}
          </Alert>
        )}

        {statsError && (
          <Alert severity="warning" sx={{ mb: 2 }} onClose={() => setStatsError('')}>
            {statsError}
          </Alert>
        )}

        <Box sx={{ mb: 3, display: 'flex', gap: 2 }}>
          <TextField
            fullWidth
            placeholder="搜索小说... (标题、类型、简介)"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            size="small"
            variant="outlined"
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon />
                </InputAdornment>
              ),
            }}
          />
        </Box>

        {filteredNovels.length === 0 ? (
          <Box sx={{ textAlign: 'center', mt: 8 }}>
            <Typography variant="h6" color="text.secondary">
              {searchQuery ? '没有找到匹配的小说' : '还没有创建任何小说'}
            </Typography>
            {!searchQuery && (
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                点击「新建小说」开始创作吧
              </Typography>
            )}
            {searchQuery && (
              <Button
                variant="text"
                onClick={() => setSearchQuery('')}
                sx={{ mt: 2 }}
              >
                清除搜索
              </Button>
            )}
          </Box>
        ) : (
          <Grid container spacing={3}>
            {filteredNovels.map((novel) => (
              <Grid item xs={12} sm={6} md={4} key={novel.id}>
                <Card>
                  <CardContent>
                    <Typography variant="h6">{novel.title}</Typography>
                    {novel.genre && (
                      <Typography variant="body2" color="text.secondary">
                        {novel.genre}
                      </Typography>
                    )}
                    {novel.description && (
                      <Typography variant="body2" sx={{ mt: 1 }}>
                        {novel.description}
                      </Typography>
                    )}
                    {novelStats[novel.id] && (
                      <Typography
                        variant="caption"
                        color="text.secondary"
                        sx={{ mt: 1, display: 'block' }}
                      >
                        {novelStats[novel.id].chapterCount} 章 · {novelStats[novel.id].totalWords} 字
                      </Typography>
                    )}
                  </CardContent>
                  <CardActions sx={{ justifyContent: 'space-between', flexDirection: 'column', alignItems: 'stretch' }}>
                    <Button variant="contained" size="small" startIcon={<EditIcon />} sx={{ mb: 1 }}
                      onClick={() => router.push(`/workspace?novel=${novel.id}`)}>进入创作工作区</Button>
                    {autoCreatingNovelId === novel.id && (
                      <Box sx={{ mb: 1 }}>
                        <LinearProgress />
                        <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
                          {generationStep}
                        </Typography>
                      </Box>
                    )}
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', width: '100%' }}>
                      <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 0.5 }}>
                        <Button
                          size="small"
                          startIcon={<AutoFixHighIcon />}
                          onClick={() => handleAutoCreateNextChapter(novel.id)}
                          disabled={autoCreatingNovelId === novel.id}
                        >
                          {autoCreatingNovelId === novel.id ? '生成中...' : 'AI生成下一章'}
                        </Button>
                        <Button
                          size="small"
                          startIcon={<MenuBookIcon />}
                          onClick={() => router.push(`/novels/${novel.id}`)}
                        >
                          章节管理
                        </Button>
                      </Box>
                      <Box>
                        <Button
                          size="small"
                          startIcon={<EditIcon />}
                          onClick={() => handleEditNovel(novel)}
                        >
                          编辑
                        </Button>
                        <Button
                          size="small"
                          color="error"
                          startIcon={<DeleteIcon />}
                          onClick={() => handleDeleteNovel(novel.id)}
                        >
                          删除
                        </Button>
                      </Box>
                    </Box>
                  </CardActions>
                </Card>
              </Grid>
            ))}
          </Grid>
        )}
      </Box>

      {/* 创建/编辑小说对话框：只有名称必填，其余可以留到工作台让 AI 补 */}
      <Dialog open={openDialog} onClose={() => setOpenDialog(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{editingNovel ? '编辑小说信息' : '新建小说'}</DialogTitle>
        <DialogContent>
          {!editingNovel && (
            <Alert severity="info" sx={{ mt: 1 }}>
              只需要一个名字就能开始。类型、简介和世界观都可以留空，之后在工作台里让 AI 帮你整理。
            </Alert>
          )}
          <TextField
            fullWidth
            label="小说名称"
            value={novelForm.title}
            onChange={(e) => setNovelForm({ ...novelForm, title: e.target.value })}
            margin="normal"
            required
            autoFocus
            placeholder="例如：长河行"
          />
          {editingNovel ? (
            <>
              <TextField
                fullWidth
                label="小说类型（可选）"
                value={novelForm.genre}
                onChange={(e) => setNovelForm({ ...novelForm, genre: e.target.value })}
                margin="normal"
                helperText="如：玄幻、都市、科幻等"
              />
              <TextField
                fullWidth
                label="小说简介（可选）"
                value={novelForm.description}
                onChange={(e) => setNovelForm({ ...novelForm, description: e.target.value })}
                margin="normal"
                multiline
                rows={3}
              />
              <TextField
                fullWidth
                label="世界观设定（可选）"
                value={novelForm.worldview}
                onChange={(e) => setNovelForm({ ...novelForm, worldview: e.target.value })}
                margin="normal"
                multiline
                rows={4}
              />
            </>
          ) : (
            <Accordion elevation={0} sx={{ mt: 2, border: 1, borderColor: 'divider', '&:before': { display: 'none' } }}>
              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                <Typography variant="body2">现在就填写更多信息（可选）</Typography>
              </AccordionSummary>
              <AccordionDetails>
                <TextField
                  fullWidth
                  label="小说类型（可选）"
                  value={novelForm.genre}
                  onChange={(e) => setNovelForm({ ...novelForm, genre: e.target.value })}
                  margin="normal"
                  helperText="如：玄幻、都市、科幻等"
                />
                <TextField
                  fullWidth
                  label="小说简介（可选）"
                  value={novelForm.description}
                  onChange={(e) => setNovelForm({ ...novelForm, description: e.target.value })}
                  margin="normal"
                  multiline
                  rows={3}
                />
                <TextField
                  fullWidth
                  label="世界观设定（可选）"
                  value={novelForm.worldview}
                  onChange={(e) => setNovelForm({ ...novelForm, worldview: e.target.value })}
                  margin="normal"
                  multiline
                  rows={4}
                />
              </AccordionDetails>
            </Accordion>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpenDialog(false)}>取消</Button>
          <Button
            onClick={handleSaveNovel}
            variant="contained"
            disabled={!novelForm.title.trim()}
          >
            {editingNovel ? '保存' : '创建并进入工作台'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* 章节预览对话框 */}
      <Dialog
        open={showChapterPreview}
        onClose={handleStayInDashboard}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <AutoFixHighIcon color="primary" />
            <Typography variant="h6">章节生成成功！</Typography>
          </Box>
        </DialogTitle>
        <DialogContent>
          {generatedChapter && (
            <Box>
              <Box sx={{ mb: 2, display: 'flex', gap: 1, alignItems: 'center' }}>
                <Chip label={`第 ${generatedChapter.chapter_number} 章`} color="primary" size="small" />
                <Chip label={`${countTextUnits(generatedChapter.content || '').toLocaleString()} 字`} size="small" />
              </Box>
              <Typography variant="h6" gutterBottom>
                {generatedChapter.title}
              </Typography>
              <Box
                sx={{
                  mt: 2,
                  p: 2,
                  bgcolor: 'background.paper',
                  borderRadius: 1,
                  border: '1px solid',
                  borderColor: 'divider',
                  maxHeight: 300,
                  overflow: 'auto',
                }}
              >
                <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', lineHeight: 1.8 }}>
                  {generatedChapter.content
                    ? generatedChapter.content.length > 300
                      ? `${generatedChapter.content.substring(0, 300)}...`
                      : generatedChapter.content
                    : '（无内容）'}
                </Typography>
              </Box>
              <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                预览仅显示前300字，完整内容请进入编辑页面查看
              </Typography>
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleStayInDashboard}>
            留在Dashboard
          </Button>
          <Button onClick={handleGoToEdit} variant="contained" startIcon={<EditIcon />}>
            进入编辑
          </Button>
        </DialogActions>
      </Dialog>
    </AppFrame>
  );
}
