'use client';

import { useEffect, useState } from 'react';
import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Stack, TextField } from '@mui/material';
import { charactersApi } from '@/lib/characters';
import type {
  CharacterCreate,
  CharacterCreateImportanceLevel,
  CharacterResponse,
  CharacterUpdate,
  CharacterUpdateImportanceLevel,
} from '@/lib/api/generated/model';

/** 重要程度作者词汇（中性阶「主力/次要/龙套」）。分类属性走 StatusChip neutral，不占状态色。 */
export const importanceLabels: Record<string, string> = { main: '主力', secondary: '次要', minor: '龙套' };

const importanceItems = [
  { value: 'main', label: importanceLabels.main },
  { value: 'secondary', label: importanceLabels.secondary },
  { value: 'minor', label: importanceLabels.minor },
] as const;

interface CharacterFormProps {
  novelId: number;
  /** 传入即编辑既有档案；null/缺省为新增。 */
  character?: CharacterResponse | null;
  open: boolean;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}

/**
 * 人物表单弹窗（弹窗尺寸映射 md=表单档）：作者语言三字段——名字、身份、重要程度。
 * 「一句话简介」无 schema 槽位，表单不设该框（预检缺口一裁决 b），档案卡以名字主行+身份副行表达。
 */
export default function CharacterForm({ novelId, character, open, onClose, onSaved }: CharacterFormProps) {
  const [name, setName] = useState('');
  const [occupation, setOccupation] = useState('');
  const [importance, setImportance] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  // 每次打开时以目标档案重置表单，避免残留上一轮输入。
  useEffect(() => {
    if (open) {
      setName(character?.name ?? '');
      setOccupation(character?.occupation ?? '');
      setImportance(character?.importance_level ?? '');
      setError('');
    }
  }, [open, character]);

  const submit = async () => {
    const trimmedName = name.trim();
    if (!trimmedName || saving) return;
    setSaving(true);
    setError('');
    try {
      if (character) {
        // 后端按 exclude_unset 增量更新；身份/重要程度清空时显式传 null，语义是「作者清掉了」。
        const payload: CharacterUpdate = {
          name: trimmedName,
          occupation: occupation.trim() ? occupation.trim() : null,
          importance_level: (importance || null) as CharacterUpdateImportanceLevel,
        };
        await charactersApi.update(character.id, payload);
      } else {
        const payload: CharacterCreate = { novel_id: novelId, name: trimmedName };
        if (occupation.trim()) payload.occupation = occupation.trim();
        if (importance) payload.importance_level = importance as CharacterCreateImportanceLevel;
        await charactersApi.create(payload);
      }
      onClose();
      await onSaved();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '保存人物档案失败');
    } finally {
      setSaving(false);
    }
  };

  return <Dialog open={open} onClose={() => { if (!saving) onClose(); }} maxWidth="md" fullWidth>
    <DialogTitle>{character ? '编辑人物档案' : '新增人物档案'}</DialogTitle>
    <DialogContent>
      <Stack spacing={2} sx={{ mt: 1 }}>
        {error && <Alert severity="error">{error}</Alert>}
        <TextField
          label="名字"
          required
          value={name}
          onChange={(event) => setName(event.target.value)}
          autoFocus
        />
        <TextField
          label="身份"
          value={occupation}
          onChange={(event) => setOccupation(event.target.value)}
          placeholder="如：游侠、国师、茶馆掌柜"
        />
        <TextField
          select
          label="重要程度"
          value={importance}
          onChange={(event) => setImportance(event.target.value)}
        >
          <MenuItem value="">未设定</MenuItem>
          {importanceItems.map((item) => <MenuItem key={item.value} value={item.value}>{item.label}</MenuItem>)}
        </TextField>
      </Stack>
    </DialogContent>
    <DialogActions>
      <Button disabled={saving} onClick={onClose}>取消</Button>
      <Button variant="contained" disabled={!name.trim() || saving} onClick={() => void submit()}>
        {saving ? '保存中…' : character ? '保存' : '创建'}
      </Button>
    </DialogActions>
  </Dialog>;
}
