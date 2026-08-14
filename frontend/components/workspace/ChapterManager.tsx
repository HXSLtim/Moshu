'use client';

import { useState, useCallback } from 'react';
import {
  Box,
  Typography,
  Button,
  List,
  ListItem,
  ListItemText,
  ListItemSecondaryAction,
  IconButton,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Alert,
  Chip,
  Menu,
  MenuItem,
  Divider,
} from '@mui/material';
import MoreVertIcon from '@mui/icons-material/MoreVert';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';
import AddIcon from '@mui/icons-material/Add';
import WarningIcon from '@mui/icons-material/Warning';
import { api } from '@/lib/api';
import type { Chapter } from '@/types';

interface ChapterManagerProps {
  novelId: number;
  chapters: Chapter[];
  currentChapter: Chapter | null;
  onChaptersUpdated: () => void;
  onChapterSelected: (chapterId: number) => void;
  onError: (error: string) => void;
}

export default function ChapterManager({
  novelId,
  chapters,
  currentChapter,
  onChaptersUpdated,
  onChapterSelected,
  onError,
}: ChapterManagerProps) {
  // 菜单状态
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);
  const [selectedChapter, setSelectedChapter] = useState<Chapter | null>(null);

  // 对话框状态
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [editDialogOpen, setEditDialogOpen] = useState(false);

  // 表单状态
  const [chapterTitle, setChapterTitle] = useState('');
  const [chapterNumber, setChapterNumber] = useState(1);
  const [loading, setLoading] = useState(false);

  // 打开菜单
  const handleMenuOpen = useCallback((event: React.MouseEvent<HTMLElement>, chapter: Chapter) => {
    setAnchorEl(event.currentTarget);
    setSelectedChapter(chapter);
  }, []);

  // 关闭菜单
  const handleMenuClose = useCallback(() => {
    setAnchorEl(null);
    setSelectedChapter(null);
  }, []);

  // 打开删除对话框
  const handleDeleteOpen = useCallback(() => {
    setDeleteDialogOpen(true);
    setAnchorEl(null);
  }, []);

  // 打开创建对话框
  const handleCreateOpen = useCallback(() => {
    const nextNumber = Math.max(...chapters.map(c => c.chapter_number), 0) + 1;
    setChapterNumber(nextNumber);
    setChapterTitle(`第${nextNumber}章`);
    setCreateDialogOpen(true);
  }, [chapters]);

  // 创建章节
  const handleCreateChapter = useCallback(async () => {
    if (!chapterTitle.trim()) {
      onError('章节标题不能为空');
      return;
    }

    setLoading(true);
    try {
      await api.createNextChapter(novelId, {
        title: chapterTitle.trim(),
        content: '',
      });
      
      setCreateDialogOpen(false);
      setChapterTitle('');
      onChaptersUpdated();
    } catch (err) {
      onError(err instanceof Error ? err.message : '创建章节失败');
    } finally {
      setLoading(false);
    }
  }, [novelId, chapterTitle, onChaptersUpdated, onError]);

  // 打开编辑对话框
  const handleEditOpen = useCallback(() => {
    if (selectedChapter) {
      setChapterTitle(selectedChapter.title);
      setChapterNumber(selectedChapter.chapter_number);
      setEditDialogOpen(true);
    }
    setAnchorEl(null);
  }, [selectedChapter]);

  // 更新章节
  const handleEditChapter = useCallback(async () => {
    if (!selectedChapter || !chapterTitle.trim()) {
      onError('章节标题不能为空');
      return;
    }

    setLoading(true);
    try {
      await api.updateChapter(novelId, selectedChapter.id, {
        title: chapterTitle.trim(),
        chapter_number: chapterNumber,
        expected_version: selectedChapter.version,
      });

      setEditDialogOpen(false);
      setChapterTitle('');
      setSelectedChapter(null);
      onChaptersUpdated();
    } catch (err) {
      onError(err instanceof Error ? err.message : '更新章节失败');
    } finally {
      setLoading(false);
    }
  }, [selectedChapter, novelId, chapterNumber, chapterTitle, onChaptersUpdated, onError]);

  // 删除章节
  const handleDeleteChapter = useCallback(async () => {
    if (!selectedChapter) return;

    setLoading(true);
    try {
      await api.deleteChapter(novelId, selectedChapter.id);

      setDeleteDialogOpen(false);
      setSelectedChapter(null);
      onChaptersUpdated();
    } catch (err) {
      onError(err instanceof Error ? err.message : '删除章节失败');
    } finally {
      setLoading(false);
    }
  }, [selectedChapter, novelId, onChaptersUpdated, onError]);

  return (
    <Box sx={{ p: 2 }}>
      <Box
        sx={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          mb: 2,
        }}
      >
        <Typography variant="h6" fontWeight="600">
          章节管理
        </Typography>
      </Box>
      
      {/* 新建章节按钮 */}
      <Button
        fullWidth
        variant="contained"
        startIcon={<AddIcon />}
        onClick={handleCreateOpen}
        sx={{ mb: 2 }}
      >
        新建章节
      </Button>
      
      <Divider sx={{ mb: 2 }} />

      {chapters.length > 0 ? (
        <List dense>
          {chapters.map((chapter) => (
            <ListItem
              key={chapter.id}
              sx={{
                border: '1px solid',
                borderColor: currentChapter?.id === chapter.id ? 'primary.main' : 'divider',
                borderRadius: 1,
                mb: 1,
                cursor: 'pointer',
                '&:hover': {
                  borderColor: 'primary.main',
                  bgcolor: 'action.hover',
                },
              }}
              onClick={() => onChapterSelected(chapter.id)}
            >
              <ListItemText
                disableTypography
                primary={
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Typography variant="body2" fontWeight="medium">
                      第{chapter.chapter_number}章
                    </Typography>
                    {currentChapter?.id === chapter.id && (
                      <Chip label="当前" size="small" color="primary" />
                    )}
                  </Box>
                }
                secondary={
                  <Box sx={{ mt: 0.5 }}>
                    <Typography variant="body2" sx={{ fontWeight: 500 }}>
                      {chapter.title}
                    </Typography>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.5 }}>
                      <Chip
                        label={`${chapter.word_count || 0} 字`}
                        size="small"
                        variant="outlined"
                      />
                      <Typography variant="caption" color="text.secondary">
                        {new Date(chapter.updated_at || chapter.created_at).toLocaleDateString()}
                      </Typography>
                    </Box>
                  </Box>
                }
              />
              <ListItemSecondaryAction>
                <IconButton
                  size="small"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleMenuOpen(e, chapter);
                  }}
                >
                  <MoreVertIcon />
                </IconButton>
              </ListItemSecondaryAction>
            </ListItem>
          ))}
        </List>
      ) : (
        <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', py: 2 }}>
          还没有章节，点击"新建章节"开始创作
        </Typography>
      )}

      {/* 章节操作菜单 */}
      <Menu
        anchorEl={anchorEl}
        open={Boolean(anchorEl)}
        onClose={handleMenuClose}
      >
        <MenuItem onClick={handleEditOpen}>
          <EditIcon sx={{ mr: 1 }} fontSize="small" />
          编辑章节
        </MenuItem>
        <MenuItem onClick={handleDeleteOpen} sx={{ color: 'error.main' }}>
          <DeleteIcon sx={{ mr: 1 }} fontSize="small" />
          删除章节
        </MenuItem>
      </Menu>

      {/* 创建章节对话框 */}
      <Dialog open={createDialogOpen} onClose={() => setCreateDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>新建章节</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            章节序号由系统按当前最后一章自动分配。
          </Typography>
          <TextField
            fullWidth
            label="章节标题"
            value={chapterTitle}
            onChange={(e) => setChapterTitle(e.target.value)}
            margin="normal"
            placeholder="例如：初入江湖"
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateDialogOpen(false)}>取消</Button>
          <Button
            variant="contained"
            onClick={handleCreateChapter}
            disabled={loading || !chapterTitle.trim()}
          >
            {loading ? '创建中...' : '创建章节'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* 编辑章节对话框 */}
      <Dialog
        open={editDialogOpen}
        onClose={() => setEditDialogOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>编辑章节</DialogTitle>
        <DialogContent>
          <TextField
            fullWidth
            label="章节序号"
            type="number"
            value={chapterNumber}
            onChange={(e) => setChapterNumber(Number(e.target.value))}
            margin="normal"
            inputProps={{ min: 1 }}
          />
          <TextField
            fullWidth
            label="章节标题"
            value={chapterTitle}
            onChange={(e) => setChapterTitle(e.target.value)}
            margin="normal"
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditDialogOpen(false)}>取消</Button>
          <Button
            variant="contained"
            onClick={handleEditChapter}
            disabled={loading || !chapterTitle.trim()}
          >
            {loading ? '保存中...' : '保存'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* 删除章节对话框 */}
      <Dialog open={deleteDialogOpen} onClose={() => setDeleteDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <WarningIcon color="error" />
          确认删除章节
        </DialogTitle>
        <DialogContent>
          <Alert severity="error" sx={{ mb: 2 }}>
            <Typography variant="body2">
              <strong>警告：此操作不可撤销！</strong>
            </Typography>
          </Alert>
          <Typography variant="body1" gutterBottom>
            您确定要删除以下章节吗？
          </Typography>
          {selectedChapter && (
            <Box sx={{ p: 2, bgcolor: 'grey.50', borderRadius: 1, mt: 2 }}>
              <Typography variant="body2" fontWeight="medium">
                第{selectedChapter.chapter_number}章 - {selectedChapter.title}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                字数: {selectedChapter.word_count || 0} 字
              </Typography>
            </Box>
          )}
          <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
            删除章节将同时清理相关的RAG向量数据和缓存。
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteDialogOpen(false)}>取消</Button>
          <Button
            variant="contained"
            color="error"
            onClick={handleDeleteChapter}
            disabled={loading}
          >
            {loading ? '删除中...' : '确认删除'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
