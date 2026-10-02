'use client';

import { useState } from 'react';
import { Alert, Box, Button, Stack, TextField, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material';
import { api } from '@/lib/api';
import type { Novel } from '@/types';

interface Props { novel: Novel; onNovelChange: (novel: Novel) => void }

/**
 * 项目信息的直接编辑入口。
 * 用自然语言整理设定走右侧创作对话里的 Agent，这里只负责手动修改。
 */
export default function ProjectInfoPanel({ novel, onNovelChange }: Props) {
  const [genre, setGenre] = useState(novel.genre || '');
  const reviewMode = (novel as { review_mode?: string }).review_mode ?? 'confirm';
  const [description, setDescription] = useState(novel.description || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const save = async () => {
    setBusy(true); setError(''); setNotice('');
    try {
      onNovelChange(await api.updateNovel(novel.id, { genre, description }));
      setNotice('已保存。');
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '保存失败');
    } finally { setBusy(false); }
  };

  return (
    <Box>
      <Typography variant="h6" gutterBottom>项目信息</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        小说名称在项目列表里改。想用说话的方式让 AI 帮你理清类型、世界观、人物和大纲，直接到右侧创作对话里说就行——它会自己判断该写什么，再让你确认。
      </Typography>
      {notice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice('')}>{notice}</Alert>}
      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}
      <Stack spacing={2}>
        <TextField fullWidth label="类型（可选）" value={genre} onChange={(event) => setGenre(event.target.value)} placeholder="如：都市奇幻、悬疑" />
        <TextField fullWidth multiline minRows={3} label="简介（可选）" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="一句话说清这本书讲什么。" />
        <Box>
          <Typography variant="caption" color="text.secondary">审核模式:AI 稿件候选的采纳方式,按本书持久保存</Typography>
          <ToggleButtonGroup exclusive size="small" value={reviewMode} onChange={(_event, value) => {
            if (!value) return;
            setBusy(true); setError(''); setNotice('');
            void api.updateNovel(novel.id, { review_mode: value }).then((saved) => { onNovelChange(saved); setNotice('审核模式已更新。'); })
              .catch((failure) => setError(failure instanceof Error ? failure.message : '更新审核模式失败'))
              .finally(() => setBusy(false));
          }}>
            <ToggleButton value="confirm" disabled={busy}>逐条确认</ToggleButton>
            <ToggleButton value="auto" disabled={busy}>自动(一致性通过才采纳)</ToggleButton>
            <ToggleButton value="none" disabled={busy}>无审核(全部采纳)</ToggleButton>
          </ToggleButtonGroup>
        </Box>
        <Box><Button variant="outlined" disabled={busy} onClick={() => void save()}>{busy ? '保存中…' : '保存项目信息'}</Button></Box>
      </Stack>
    </Box>
  );
}
