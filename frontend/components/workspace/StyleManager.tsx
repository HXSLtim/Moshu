'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  Card,
  CardContent,
  Typography,
  Button,
  Box,
  Divider,
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
  Chip,
  Alert,
  FormControlLabel,
  Switch,
} from '@mui/material';
import PaletteIcon from '@mui/icons-material/Palette';
import AddIcon from '@mui/icons-material/Add';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';
import { api } from '@/lib/api';
import type { StyleSample } from '@/types';

interface StyleManagerProps {
  novelId: number;
  selectedStyleSampleId: number | null;
  onStyleSampleSelected: (sampleId: number | null) => void;
  onError: (error: string) => void;
}

export default function StyleManager({
  novelId,
  selectedStyleSampleId,
  onStyleSampleSelected,
  onError,
}: StyleManagerProps) {
  const [styleSamples, setStyleSamples] = useState<StyleSample[]>([]);
  const [loading, setLoading] = useState(false);
  
  // 对话框状态
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingSample, setEditingSample] = useState<StyleSample | null>(null);
  const [sampleName, setSampleName] = useState('');
  const [sampleText, setSampleText] = useState('');
  const [saving, setSaving] = useState(false);

  // 加载文风样本
  const loadStyleSamples = useCallback(async () => {
    setLoading(true);
    try {
      console.log('正在加载文风样本，novelId:', novelId);
      const samples = await api.getStyleSamples(novelId);
      console.log('加载到的文风样本:', samples);
      setStyleSamples(samples);
    } catch (err) {
      console.error('加载文风样本失败:', err);
      onError(err instanceof Error ? err.message : '加载文风样本失败');
    } finally {
      setLoading(false);
    }
  }, [novelId, onError]);

  // 创建新样本
  const handleCreateSample = useCallback(() => {
    setEditingSample(null);
    setSampleName('');
    setSampleText('');
    setDialogOpen(true);
  }, []);

  // 编辑样本
  const handleEditSample = useCallback((sample: StyleSample) => {
    setEditingSample(sample);
    setSampleName(sample.name);
    setSampleText(sample.sample_preview);
    setDialogOpen(true);
  }, []);

  // 保存样本
  const handleSaveSample = useCallback(async () => {
    if (!sampleName.trim() || !sampleText.trim()) {
      onError('样本名称和文本不能为空');
      return;
    }

    setSaving(true);
    try {
      if (editingSample) {
        // 编辑现有样本（这里需要API支持更新）
        // await api.updateStyleSample(editingSample.id, { name: sampleName, sample_text: sampleText });
        onError('编辑功能暂未实现');
      } else {
        // 创建新样本
        await api.createStyleSample({
          novel_id: novelId,
          name: sampleName.trim(),
          sample_text: sampleText.trim(),
        });
      }
      
      setDialogOpen(false);
      loadStyleSamples();
    } catch (err) {
      onError(err instanceof Error ? err.message : '保存文风样本失败');
    } finally {
      setSaving(false);
    }
  }, [editingSample, sampleName, sampleText, novelId, onError, loadStyleSamples]);

  // 删除样本
  const handleDeleteSample = useCallback(async (sampleId: number) => {
    void sampleId;
    if (!confirm('确定要删除这个文风样本吗？')) {
      return;
    }

    try {
      // await api.deleteStyleSample(sampleId);
      onError('删除功能暂未实现');
      // loadStyleSamples();
    } catch (err) {
      onError(err instanceof Error ? err.message : '删除文风样本失败');
    }
  }, [onError]);

  // 选择样本
  const handleSelectSample = useCallback((sampleId: number | null) => {
    onStyleSampleSelected(sampleId);
  }, [onStyleSampleSelected]);

  // 组件挂载时加载样本
  useEffect(() => {
    loadStyleSamples();
  }, [loadStyleSamples]);

  return (
    <>
      <Card sx={{ mb: 2 }}>
        <CardContent>
          <Box
            sx={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              mb: 1,
            }}
          >
            <Typography variant="subtitle2">文风样本</Typography>
            <Button
              size="small"
              variant="outlined"
              startIcon={<AddIcon />}
              onClick={handleCreateSample}
            >
              新建样本
            </Button>
          </Box>
          <Divider sx={{ my: 1 }} />

          {loading ? (
            <Typography variant="body2" color="text.secondary">
              加载中...
            </Typography>
          ) : styleSamples.length > 0 ? (
            <Box>
              {/* 无样本选项 */}
              <Box sx={{ mb: 2 }}>
                <FormControlLabel
                  control={
                    <Switch
                      checked={selectedStyleSampleId === null}
                      onChange={(e) => handleSelectSample(e.target.checked ? null : styleSamples[0]?.id || null)}
                    />
                  }
                  label="使用默认文风"
                />
              </Box>

              {/* 样本列表 */}
              <List dense>
                {styleSamples.map((sample) => (
                  <ListItem
                    key={sample.id}
                    sx={{
                      border: '1px solid',
                      borderColor: selectedStyleSampleId === sample.id ? 'primary.main' : 'divider',
                      borderRadius: 1,
                      mb: 1,
                      cursor: 'pointer',
                      '&:hover': {
                        borderColor: 'primary.main',
                      },
                    }}
                    onClick={() => handleSelectSample(sample.id)}
                  >
                    <ListItemText
                      disableTypography
                      primary={
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                          <PaletteIcon color="primary" fontSize="small" />
                          <Typography variant="body2" fontWeight="medium">
                            {sample.name}
                          </Typography>
                          {selectedStyleSampleId === sample.id && (
                            <Chip label="已选择" size="small" color="primary" />
                          )}
                        </Box>
                      }
                      secondary={
                        <Box sx={{ mt: 1 }}>
                          <Typography
                            variant="caption"
                            color="text.secondary"
                            sx={{
                              display: 'block',
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                            }}
                          >
                            {sample.sample_preview}
                          </Typography>
                          
                          {sample.style_features.length > 0 && (
                            <Box sx={{ display: 'flex', gap: 0.5, mt: 1, flexWrap: 'wrap' }}>
                              {sample.style_features.slice(0, 3).map((feature, idx) => (
                                <Chip
                                  key={idx}
                                  label={feature}
                                  size="small"
                                  variant="outlined"
                                  sx={{ fontSize: '0.7rem', height: 20 }}
                                />
                              ))}
                              {sample.style_features.length > 3 && (
                                <Chip
                                  label={`+${sample.style_features.length - 3}`}
                                  size="small"
                                  variant="outlined"
                                  sx={{ fontSize: '0.7rem', height: 20 }}
                                />
                              )}
                            </Box>
                          )}
                        </Box>
                      }
                    />
                    <ListItemSecondaryAction>
                      <IconButton
                        size="small"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleEditSample(sample);
                        }}
                      >
                        <EditIcon fontSize="small" />
                      </IconButton>
                      <IconButton
                        size="small"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeleteSample(sample.id);
                        }}
                      >
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </ListItemSecondaryAction>
                  </ListItem>
                ))}
              </List>
            </Box>
          ) : (
            <Box>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                还没有文风样本。创建样本可以让AI学习您的写作风格。
              </Typography>
              <Alert severity="info">
                <Typography variant="body2">
                  文风样本是一段具有特定写作风格的文本，AI会分析其语言特征并在续写时模仿这种风格。
                </Typography>
              </Alert>
            </Box>
          )}
        </CardContent>
      </Card>

      {/* 创建/编辑样本对话框 */}
      <Dialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>
          {editingSample ? '编辑文风样本' : '新建文风样本'}
        </DialogTitle>
        <DialogContent>
          <TextField
            fullWidth
            label="样本名称"
            value={sampleName}
            onChange={(e) => setSampleName(e.target.value)}
            margin="normal"
            placeholder="例如：古典文风、现代都市、科幻风格..."
          />
          <TextField
            fullWidth
            label="样本文本"
            value={sampleText}
            onChange={(e) => setSampleText(e.target.value)}
            margin="normal"
            multiline
            rows={8}
            placeholder="请输入一段具有特定风格的文本，AI将学习其语言特征..."
            helperText="建议输入200-500字的文本，包含完整的句子和段落结构"
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>取消</Button>
          <Button
            variant="contained"
            onClick={handleSaveSample}
            disabled={saving || !sampleName.trim() || !sampleText.trim()}
          >
            {saving ? '保存中...' : editingSample ? '更新样本' : '创建样本'}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
