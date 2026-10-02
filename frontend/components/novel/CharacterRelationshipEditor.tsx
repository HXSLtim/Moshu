'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Slider,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { charactersApi } from '@/lib/characters';
import { EmptyState, SectionHeader } from '@/components/common/primitives';
import CharacterRelationshipGraph from './CharacterRelationshipGraph';
import type {
  CharacterRelationshipResponse,
  CharacterResponse,
} from '@/lib/api/generated/model';

/** 关系类型常用候选；自由输入不受限（schema 为自由字符串，长度 50）。 */
const relationshipTypeCandidates = ['亲人', '挚友', '师徒', '恋人', '同盟', '敌对'];

interface CharacterRelationshipEditorProps {
  novelId: number;
}

/**
 * 人物关系区：手绘 SVG 关系图 + 三步入表单（人物一 → 人物二 → 关系类型）+ 关系卡。
 * REST 与 MCP 均无删除端点（预检缺口二），关系卡只提供编辑并诚实告知不支持删除；
 * 编辑经 MCP update_relationship，服务端对四字段全量覆盖，
 * 未在界面暴露的 development_stage 原样透传防清空。
 */
export default function CharacterRelationshipEditor({ novelId }: CharacterRelationshipEditorProps) {
  const [characters, setCharacters] = useState<CharacterResponse[]>([]);
  const [relationships, setRelationships] = useState<CharacterRelationshipResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const controllerRef = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setLoading(true);
    setError('');
    try {
      const network = await charactersApi.network(novelId, controller.signal);
      if (!controller.signal.aborted) {
        setCharacters(network.characters);
        setRelationships(network.relationships);
      }
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : '读取人物关系失败');
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [novelId]);

  useEffect(() => {
    void load();
    return () => controllerRef.current?.abort();
  }, [load]);

  // 建立关系表单（三步入：人物一 → 人物二 → 关系类型，余下可选）。
  const [personA, setPersonA] = useState('');
  const [personB, setPersonB] = useState('');
  const [type, setType] = useState('');
  const [strength, setStrength] = useState(5);
  const [description, setDescription] = useState('');
  const [established, setEstablished] = useState('');
  const [creating, setCreating] = useState(false);

  // 编辑关系弹窗。
  const [editing, setEditing] = useState<CharacterRelationshipResponse | null>(null);
  const [editType, setEditType] = useState('');
  const [editStrength, setEditStrength] = useState(5);
  const [editDescription, setEditDescription] = useState('');
  const [saving, setSaving] = useState(false);
  const [dialogError, setDialogError] = useState('');

  const addRelationship = async () => {
    if (!personA || !personB || personA === personB || !type.trim() || creating) return;
    setCreating(true);
    setError('');
    try {
      await charactersApi.createRelationship({
        novel_id: novelId,
        character_a_id: Number(personA),
        character_b_id: Number(personB),
        relationship_type: type.trim(),
        strength,
        description: description.trim() ? description.trim() : null,
        established_in_chapter: established ? Number(established) : null,
      });
      setPersonB('');
      setType('');
      setStrength(5);
      setDescription('');
      setEstablished('');
      await load();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '建立关系失败');
    } finally {
      setCreating(false);
    }
  };

  const openEdit = (relationship: CharacterRelationshipResponse) => {
    setEditing(relationship);
    setEditType(relationship.relationship_type);
    setEditStrength(relationship.strength ?? 5);
    setEditDescription(relationship.description ?? '');
    setDialogError('');
  };

  const saveEdit = async () => {
    if (!editing || !editType.trim() || saving) return;
    setSaving(true);
    setDialogError('');
    try {
      const response = await charactersApi.executeMcpAction({
        action: 'update_relationship',
        parameters: {
          relationship_id: editing.id,
          relationship_type: editType.trim(),
          strength: editStrength,
          description: editDescription.trim() ? editDescription.trim() : null,
          development_stage: editing.development_stage ?? null,
        },
      });
      if (!response.success) throw new Error(response.message || '关系更新失败');
      setEditing(null);
      await load();
    } catch (failure) {
      setDialogError(failure instanceof Error ? failure.message : '关系更新失败');
    } finally {
      setSaving(false);
    }
  };

  return <Card elevation={0} sx={{ border: 1, borderColor: 'divider', mt: 3 }}>
    <CardContent sx={{ p: { xs: 2, sm: 3 } }}>
      <SectionHeader title="人物关系" />
      <Typography variant="body2" color="text.secondary">把人物连成网络：谁与谁是何种关系。AI 写对手戏时会读到这里的关系事实。</Typography>
      {error && <Alert severity="error" sx={{ mt: 2 }} action={<Button color="inherit" onClick={() => void load()}>重试</Button>}>{error}</Alert>}
      {loading && <Typography role="status" sx={{ mt: 2 }}>正在读取人物关系…</Typography>}
      {!loading && !error && characters.length === 0 && <Box sx={{ mt: 2 }}>
        <EmptyState title="还没有人物关系。" hint="先在上方人物档案区创建人物，再回来建立关系。" />
      </Box>}
      {!loading && !error && characters.length > 0 && <Box sx={{ mt: 2 }}>
        {relationships.length > 0
          ? <CharacterRelationshipGraph characters={characters} relationships={relationships} />
          : <EmptyState title="还没有人物关系。" hint="用下方表单给两个人物建立第一段关系，关系图会随之连线。" />}
        <Box sx={{ mt: 3 }}>
          <SectionHeader title="建立关系" />
          <Stack spacing={2}>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
              <TextField
                select
                label="人物一"
                value={personA}
                onChange={(event) => setPersonA(event.target.value)}
                fullWidth
              >
                {characters.map((character) => <MenuItem key={character.id} value={String(character.id)}>{character.name}</MenuItem>)}
              </TextField>
              <TextField
                select
                label="人物二"
                value={personB}
                onChange={(event) => setPersonB(event.target.value)}
                fullWidth
              >
                {characters.map((character) => <MenuItem key={character.id} value={String(character.id)}>{character.name}</MenuItem>)}
              </TextField>
            </Stack>
            <TextField
              label="关系类型"
              value={type}
              onChange={(event) => setType(event.target.value)}
              placeholder="如：亲人、师徒、敌对…"
              helperText="可写明方向（如「师徒」），细节放进描述。"
            />
            <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: 'wrap' }}>
              {relationshipTypeCandidates.map((candidate) => (
                <Button key={candidate} size="small" onClick={() => setType(candidate)}>{candidate}</Button>
              ))}
            </Stack>
            <Box>
              <Typography variant="body2" color="text.secondary">关系强度：{strength}/10</Typography>
              <Slider
                aria-label="关系强度"
                value={strength}
                min={1}
                max={10}
                step={1}
                marks
                valueLabelDisplay="auto"
                onChange={(_, value) => setStrength(value as number)}
              />
            </Box>
            <TextField
              label="描述"
              multiline
              rows={2}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
            <TextField
              label="确立章节"
              type="number"
              value={established}
              onChange={(event) => setEstablished(event.target.value)}
              helperText="可选。这段关系在叙事里的确立位置。"
              sx={{ maxWidth: 220 }}
            />
            {personA && personA === personB && <Typography variant="body2" sx={{ color: 'error.main' }}>两个人物不能是同一位。</Typography>}
            <Box>
              <Button
                variant="contained"
                disabled={!personA || !personB || personA === personB || !type.trim() || creating}
                onClick={() => void addRelationship()}
              >
                {creating ? '建立中…' : '建立关系'}
              </Button>
            </Box>
          </Stack>
        </Box>
        {relationships.length > 0 && <Box sx={{ mt: 3 }}>
          <SectionHeader title="已建立的关系" />
          <Stack spacing={1.5}>
            {relationships.map((relationship) => <Box key={relationship.id} sx={{ border: 1, borderColor: 'divider', borderRadius: 1, p: 2 }}>
              <Stack direction="row" justifyContent="space-between" alignItems="flex-start" gap={2}>
                <Box sx={{ minWidth: 0 }}>
                  <Typography variant="subtitle1">{relationship.character_a_name} —— {relationship.relationship_type} —— {relationship.character_b_name}</Typography>
                  <Typography variant="caption" color="text.secondary">
                    {[
                      relationship.strength != null ? `强度 ${relationship.strength}/10` : null,
                      relationship.established_in_chapter != null ? `第 ${relationship.established_in_chapter} 章确立` : null,
                    ].filter(Boolean).join(' · ')}
                  </Typography>
                  {relationship.description && <Typography variant="body2" sx={{ mt: 0.5 }}>{relationship.description}</Typography>}
                </Box>
                <Button
                  size="small"
                  aria-label={`编辑${relationship.character_a_name}与${relationship.character_b_name}的关系`}
                  onClick={() => openEdit(relationship)}
                >编辑</Button>
              </Stack>
            </Box>)}
          </Stack>
          <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>关系暂不支持删除；要调整就编辑类型或描述。</Typography>
        </Box>}
      </Box>}
      <Dialog open={Boolean(editing)} onClose={() => { if (!saving) setEditing(null); }} maxWidth="md" fullWidth>
        <DialogTitle>编辑关系</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            {dialogError && <Alert severity="error">{dialogError}</Alert>}
            <TextField
              label="关系类型"
              value={editType}
              onChange={(event) => setEditType(event.target.value)}
            />
            <Box>
              <Typography variant="body2" color="text.secondary">关系强度：{editStrength}/10</Typography>
              <Slider
                aria-label="关系强度"
                value={editStrength}
                min={1}
                max={10}
                step={1}
                marks
                valueLabelDisplay="auto"
                onChange={(_, value) => setEditStrength(value as number)}
              />
            </Box>
            <TextField
              label="描述"
              multiline
              rows={2}
              value={editDescription}
              onChange={(event) => setEditDescription(event.target.value)}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button disabled={saving} onClick={() => setEditing(null)}>取消</Button>
          <Button variant="contained" disabled={!editType.trim() || saving} onClick={() => void saveEdit()}>
            {saving ? '保存中…' : '保存'}
          </Button>
        </DialogActions>
      </Dialog>
    </CardContent>
  </Card>;
}
