'use client';
import { useState } from 'react';
import { Alert, Button, Card, CardContent, Stack, TextField, Typography } from '@mui/material';
import { api } from '@/lib/api';
import type { Novel } from '@/types';

export default function WorldviewEditor({ novel }: { novel: Novel }) {
  const [text, setText] = useState(novel.worldview ?? '');
  const [saved, setSaved] = useState(novel.worldview ?? '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const save = async () => {
    setSaving(true);
    setError('');
    setSuccess(false);
    try {
      const updated = await api.updateNovel(novel.id, { worldview: text });
      setText(updated.worldview ?? '');
      setSaved(updated.worldview ?? '');
      setSuccess(true);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '保存世界观失败，编辑内容已保留');
    } finally { setSaving(false); }
  };
  return <Card sx={{ my: 3 }}><CardContent>
    <Typography variant="h6" sx={{ mb: 2 }}>世界观总览</Typography>
    {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
    {success && <Alert severity="success" sx={{ mb: 2 }}>世界观已保存</Alert>}
    <TextField fullWidth multiline minRows={4} maxRows={12} label="世界观设定" value={text} disabled={saving}
      slotProps={{ htmlInput: { maxLength: 50000 } }} helperText="记录故事背景和基本规则；具体人物状态、事件与伏笔可在下方分条维护。"
      onChange={(event) => { setText(event.target.value); setSuccess(false); }} />
    <Stack direction="row" gap={1} sx={{ mt: 2 }}>
      <Button variant="contained" disabled={saving || text === saved} onClick={() => void save()}>{saving ? '保存中…' : '保存世界观'}</Button>
      <Button disabled={saving || text === saved} onClick={() => { setText(saved); setError(''); }}>放弃修改</Button>
    </Stack>
  </CardContent></Card>;
}

