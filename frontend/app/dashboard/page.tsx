'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Container,
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
} from '@mui/material';
import InputAdornment from '@mui/material/InputAdornment';
import AddIcon from '@mui/icons-material/Add';
import LogoutIcon from '@mui/icons-material/Logout';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';
import MenuBookIcon from '@mui/icons-material/MenuBook';
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh';
import SearchIcon from '@mui/icons-material/Search';
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
  const [quickCreateDialogOpen, setQuickCreateDialogOpen] = useState(false);
  const [quickCreateTheme, setQuickCreateTheme] = useState('');
  const [quickCreateLoading, setQuickCreateLoading] = useState(false);
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

  const handleCreateNovel = () => {
    setNovelForm({ title: '', genre: '', description: '', worldview: '' });
    setEditingNovel(null);
    setOpenDialog(true);
  };

  const handleOpenQuickCreate = () => {
    setQuickCreateTheme('');
    setQuickCreateDialogOpen(true);
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
    try {
      if (editingNovel) {
        await api.updateNovel(editingNovel.id, novelForm);
      } else {
        await api.createNovel(novelForm);
      }
      setOpenDialog(false);
      if (typeof window !== 'undefined') {
        const draftKey = editingNovel
          ? `novel_form_draft_edit_${editingNovel.id}`
          : 'novel_form_draft_new';
        window.localStorage.removeItem(draftKey);
      }
      await loadNovels();
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    }
  };

  const handleQuickCreateNovel = async () => {
    try {
      setQuickCreateLoading(true);
      const theme = quickCreateTheme.trim();
      const baseTitle = theme || '未命名小说';
      const title = baseTitle.length > 20 ? baseTitle.slice(0, 20) : baseTitle;

      const novel = await api.createNovel({
        title,
        genre: '',
        description: theme,
        worldview: '',
      });

      try {
        if (theme) {
          const initResult = await api.initNovel({
            novel_id: novel.id,
            target_chapters: 10,
            theme,
          });

          const combinedWorldview = `【世界观】\n${initResult.worldview}\n\n【主要角色】\n${
            initResult.main_characters && initResult.main_characters.length > 0
              ? initResult.main_characters.join('\n')
              : ''
          }\n\n【章节大纲】\n${initResult.outline}\n\n【剧情线索】\n${
            initResult.plot_hooks && initResult.plot_hooks.length > 0
              ? initResult.plot_hooks.join('\n')
              : ''
          }`;

          await api.updateNovel(novel.id, {
            worldview: combinedWorldview,
          });
        }
      } catch {
        // 初始化失败不影响小说创建
      }

      setQuickCreateDialogOpen(false);
      setQuickCreateTheme('');
      router.push(`/novels/${novel.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : '一键创建小说失败');
    } finally {
      setQuickCreateLoading(false);
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
      <Container maxWidth="lg">
        <Box sx={{ mt: 4, textAlign: 'center' }}>
          <Typography>加载中...</Typography>
        </Box>
      </Container>
    );
  }

  return (
    <Container maxWidth="lg">
      <Box sx={{ mt: 4, mb: 4 }}>
        <Box sx={{ mb: 3 }}>
          <Card>
            <CardContent>
              <Typography variant="h5" gutterBottom>
                一站式 AI 小说写作
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                说一句话开始新故事，或一键回到上次写作位置。
              </Typography>
              <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
                <Button
                  variant="contained"
                  onClick={handleOpenQuickCreate}
                  disabled={loading}
                >
                  一键开始新小说（AI 带写）
                </Button>
                {lastWorkspace ? (
                  <Button
                    variant="outlined"
                    onClick={() => {
                      router.push(`/workspace?novel=${lastWorkspace.novelId}&chapter=${lastWorkspace.chapterId}`);
                    }}
                  >
                    继续上次写作
                  </Button>
                ) : (
                  <Typography variant="body2" color="text.secondary">
                    暂无最近编辑的小说
                  </Typography>
                )}
              </Box>
            </CardContent>
          </Card>
        </Box>

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

        <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 3 }}>
          <Typography variant="h4">我的小说</Typography>
          <Box>
            <Button
              variant="contained"
              startIcon={<AddIcon />}
              onClick={handleCreateNovel}
              sx={{ mr: 2 }}
            >
              新建小说
            </Button>
            <Button
              variant="outlined"
              startIcon={<LogoutIcon />}
              onClick={handleLogout}
            >
              退出登录
            </Button>
          </Box>
        </Box>

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

      {/* 创建/编辑小说对话框 */}
      <Dialog open={openDialog} onClose={() => setOpenDialog(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{editingNovel ? '编辑小说' : '新建小说'}</DialogTitle>
        <DialogContent>
          <TextField
            fullWidth
            label="小说标题"
            value={novelForm.title}
            onChange={(e) => setNovelForm({ ...novelForm, title: e.target.value })}
            margin="normal"
            required
            autoFocus
          />
          <TextField
            fullWidth
            label="小说类型"
            value={novelForm.genre}
            onChange={(e) => setNovelForm({ ...novelForm, genre: e.target.value })}
            margin="normal"
            helperText="如：玄幻、都市、科幻等"
          />
          <TextField
            fullWidth
            label="小说简介"
            value={novelForm.description}
            onChange={(e) => setNovelForm({ ...novelForm, description: e.target.value })}
            margin="normal"
            multiline
            rows={3}
          />
          <TextField
            fullWidth
            label="世界观设定"
            value={novelForm.worldview}
            onChange={(e) => setNovelForm({ ...novelForm, worldview: e.target.value })}
            margin="normal"
            multiline
            rows={4}
            helperText="描述小说的世界观、设定等"
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpenDialog(false)}>取消</Button>
          <Button
            onClick={handleSaveNovel}
            variant="contained"
            disabled={!novelForm.title}
          >
            {editingNovel ? '保存' : '创建'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* 一键开始新小说对话框 */}
      <Dialog
        open={quickCreateDialogOpen}
        onClose={() => {
          if (quickCreateLoading) return;
          setQuickCreateDialogOpen(false);
        }}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>一键开始新小说（AI 带写）</DialogTitle>
        <DialogContent>
          <TextField
            fullWidth
            label="用一句话描述你想写的故事"
            value={quickCreateTheme}
            onChange={(e) => setQuickCreateTheme(e.target.value)}
            margin="normal"
            multiline
            rows={3}
            placeholder="例如：一名落魄魔法师重返学院复仇，却发现真正的敌人另有其人"
          />
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => setQuickCreateDialogOpen(false)}
            disabled={quickCreateLoading}
          >
            取消
          </Button>
          <Button
            onClick={handleQuickCreateNovel}
            variant="contained"
            disabled={quickCreateLoading}
          >
            {quickCreateLoading ? '生成中...' : '一键生成'}
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
                <Chip label={`${generatedChapter.content?.length || 0} 字`} size="small" />
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
    </Container>
  );
}
