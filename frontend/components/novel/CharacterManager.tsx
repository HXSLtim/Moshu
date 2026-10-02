'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Box, Button, Card, CardContent, Dialog, DialogActions, DialogContent, DialogTitle, Stack, Typography } from '@mui/material';
import { charactersApi } from '@/lib/characters';
import { EmptyState, SectionHeader, StatusChip } from '@/components/common/primitives';
import type { CharacterResponse } from '@/lib/api/generated/model';

const importanceLabels: Record<string, string> = { main: '主力', secondary: '次要', minor: '龙套' };

/**
 * 人物档案管理区（管理密度档样板）：一级卡 + 内嵌条目卡两级封顶，读/删闭环。
 * 新增与编辑表单由后续组件提供；界面零系统词，色只用主题 token。
 */
export default function CharacterManager({ novelId }: { novelId: number }) {
  const [characters, setCharacters] = useState<CharacterResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [deleting, setDeleting] = useState<CharacterResponse | null>(null);
  const [saving, setSaving] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setLoading(true);
    setError('');
    try {
      const items = await charactersApi.list(novelId, controller.signal);
      if (!controller.signal.aborted) setCharacters(items);
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : '读取人物档案失败');
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [novelId]);

  useEffect(() => {
    void load();
    return () => controllerRef.current?.abort();
  }, [load]);

  const remove = async () => {
    if (!deleting || saving) return;
    setSaving(true);
    setError('');
    try {
      await charactersApi.remove(deleting.id);
      setDeleting(null);
      await load();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '删除失败');
    } finally {
      setSaving(false);
    }
  };

  return <Card elevation={0} sx={{ border: 1, borderColor: 'divider', mt: 3 }}>
    <CardContent sx={{ p: { xs: 2, sm: 3 } }}>
      <SectionHeader title="人物档案" />
      <Typography variant="body2" color="text.secondary">全书的人物资产库：集中管理名字、身份与重要程度，AI 写作时会读到这里的内容。</Typography>
      {error && <Alert severity="error" sx={{ mt: 2 }} action={<Button color="inherit" onClick={() => void load()}>重试</Button>}>{error}</Alert>}
      {loading && <Typography role="status" sx={{ mt: 2 }}>正在读取人物档案…</Typography>}
      {!loading && !error && characters.length === 0 && <Box sx={{ mt: 2 }}>
        <EmptyState title="还没有人物档案。" hint="在对话里让 Nai 整理设定并确认写入后，人物会出现在这里。" />
      </Box>}
      <Stack spacing={2} sx={{ mt: 2 }}>
        {characters.map((character) => <Box key={character.id} sx={{ border: 1, borderColor: 'divider', borderRadius: 1, p: 2 }}>
          <Stack direction="row" justifyContent="space-between" alignItems="flex-start" gap={2}>
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="subtitle1">{character.name}</Typography>
              {character.occupation && <Typography variant="body2" color="text.secondary">{character.occupation}</Typography>}
            </Box>
            {character.importance_level && <StatusChip tone="neutral" size="small" label={importanceLabels[character.importance_level] ?? character.importance_level} />}
          </Stack>
          <Stack direction="row" gap={1} sx={{ mt: 1.5 }}>
            <Button size="small" color="error" aria-label={`删除${character.name}`} onClick={() => { setError(''); setDeleting(character); }}>删除</Button>
          </Stack>
        </Box>)}
      </Stack>
      <Dialog open={Boolean(deleting)} onClose={() => { if (!saving) setDeleting(null); }}>
        <DialogTitle>删除人物档案</DialogTitle>
        <DialogContent>
          <Typography>确定删除「{deleting?.name}」？此操作不能撤销。</Typography>
        </DialogContent>
        <DialogActions>
          <Button disabled={saving} onClick={() => setDeleting(null)}>取消</Button>
          <Button color="error" disabled={saving} onClick={() => void remove()}>确认删除</Button>
        </DialogActions>
      </Dialog>
    </CardContent>
  </Card>;
}
