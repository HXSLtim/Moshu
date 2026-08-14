'use client';

import { useState, useCallback } from 'react';
import {
  Card,
  CardContent,
  Typography,
  Button,
  Box,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  TextField,
  Divider,
  Chip,
} from '@mui/material';
import EditIcon from '@mui/icons-material/Edit';
import { api } from '@/lib/api';

interface TextRewriterProps {
  novelId: number;
  chapterId: number | null;
  selectedText: string;
  selectionStart: number | null;
  selectionEnd: number | null;
  onTextRewritten: (newText: string, start: number, end: number) => void;
  onError: (error: string) => void;
}

export default function TextRewriter({
  novelId,
  chapterId,
  selectedText,
  selectionStart,
  selectionEnd,
  onTextRewritten,
  onError,
}: TextRewriterProps) {
  const [rewriteType, setRewriteType] = useState<'polish' | 'rewrite' | 'shorten' | 'extend'>('polish');
  const [styleHint, setStyleHint] = useState('');
  const [targetLength, setTargetLength] = useState<number | undefined>(undefined);
  const [rewriteLoading, setRewriteLoading] = useState(false);
  const [rewrittenText, setRewrittenText] = useState('');

  const rewriteTypeLabels = {
    polish: '润色优化',
    rewrite: '重新改写',
    shorten: '精简缩短',
    extend: '扩展延伸',
  };

  const handleRewrite = useCallback(async () => {
    if (!selectedText || !chapterId) {
      onError('请先选择要改写的文本');
      return;
    }

    setRewriteLoading(true);
    setRewrittenText('');

    try {
      const result = await api.rewriteText({
        novel_id: novelId,
        chapter_id: chapterId,
        original_text: selectedText,
        rewrite_type: rewriteType,
        style_hint: styleHint || undefined,
        target_length: targetLength,
      });

      setRewrittenText(result.rewritten_text);
    } catch (err) {
      onError(err instanceof Error ? err.message : '改写失败');
    } finally {
      setRewriteLoading(false);
    }
  }, [novelId, chapterId, selectedText, rewriteType, styleHint, targetLength, onError]);

  const handleApplyRewrite = useCallback(() => {
    if (rewrittenText && selectionStart !== null && selectionEnd !== null) {
      onTextRewritten(rewrittenText, selectionStart, selectionEnd);
      setRewrittenText('');
    }
  }, [rewrittenText, selectionStart, selectionEnd, onTextRewritten]);

  const handleDiscardRewrite = useCallback(() => {
    setRewrittenText('');
  }, []);

  if (!selectedText) {
    return (
      <Card sx={{ mb: 2 }}>
        <CardContent>
          <Typography variant="subtitle2" gutterBottom>
            局部改写
          </Typography>
          <Divider sx={{ my: 1 }} />
          <Typography variant="body2" color="text.secondary">
            请在编辑器中选择要改写的文本
          </Typography>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card sx={{ mb: 2 }}>
      <CardContent>
        <Typography variant="subtitle2" gutterBottom>
          局部改写
        </Typography>
        <Divider sx={{ my: 1 }} />

        {/* 选中文本显示 */}
        <Box sx={{ mb: 2 }}>
          <Typography variant="caption" color="text.secondary" gutterBottom>
            选中的文本:
          </Typography>
          <Box
            sx={{
              p: 1.5,
              bgcolor: 'primary.50',
              borderRadius: 1,
              border: '1px solid',
              borderColor: 'primary.200',
              maxHeight: 100,
              overflow: 'auto',
            }}
          >
            <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
              {selectedText}
            </Typography>
          </Box>
          <Chip
            label={`${selectedText.length} 字`}
            size="small"
            sx={{ mt: 1 }}
          />
        </Box>

        {/* 改写类型选择 */}
        <FormControl fullWidth sx={{ mb: 2 }}>
          <InputLabel>改写类型</InputLabel>
          <Select
            value={rewriteType}
            onChange={(e) => setRewriteType(e.target.value as typeof rewriteType)}
            disabled={rewriteLoading}
          >
            {Object.entries(rewriteTypeLabels).map(([value, label]) => (
              <MenuItem key={value} value={value}>
                {label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        {/* 风格提示 */}
        <TextField
          fullWidth
          label="风格提示（可选）"
          value={styleHint}
          onChange={(e) => setStyleHint(e.target.value)}
          placeholder="例如：更加正式、增加情感色彩、使用古典文风..."
          sx={{ mb: 2 }}
          disabled={rewriteLoading}
        />

        {/* 目标长度（仅对扩展和缩短有效） */}
        {(rewriteType === 'extend' || rewriteType === 'shorten') && (
          <TextField
            fullWidth
            type="number"
            label="目标长度（字数）"
            value={targetLength || ''}
            onChange={(e) => setTargetLength(e.target.value ? Number(e.target.value) : undefined)}
            sx={{ mb: 2 }}
            disabled={rewriteLoading}
          />
        )}

        {/* 改写按钮 */}
        <Button
          fullWidth
          variant="contained"
          startIcon={<EditIcon />}
          onClick={handleRewrite}
          disabled={rewriteLoading || !chapterId}
          sx={{ mb: 2 }}
        >
          {rewriteLoading ? '改写中...' : `开始${rewriteTypeLabels[rewriteType]}`}
        </Button>

        {/* 改写结果 */}
        {rewrittenText && (
          <Box>
            <Typography variant="caption" color="text.secondary" gutterBottom>
              改写结果:
            </Typography>
            <Box
              sx={{
                p: 1.5,
                bgcolor: 'success.50',
                borderRadius: 1,
                border: '1px solid',
                borderColor: 'success.200',
                maxHeight: 150,
                overflow: 'auto',
                mb: 2,
              }}
            >
              <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
                {rewrittenText}
              </Typography>
            </Box>
            <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
              <Chip
                label={`原文: ${selectedText.length} 字`}
                size="small"
                variant="outlined"
              />
              <Chip
                label={`改写: ${rewrittenText.length} 字`}
                size="small"
                color="success"
              />
            </Box>
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Button
                variant="contained"
                size="small"
                onClick={handleApplyRewrite}
              >
                应用改写
              </Button>
              <Button
                variant="outlined"
                size="small"
                onClick={handleDiscardRewrite}
              >
                丢弃
              </Button>
            </Box>
          </Box>
        )}
      </CardContent>
    </Card>
  );
}
