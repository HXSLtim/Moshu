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
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { api } from '@/lib/api';
import { charactersApi } from '@/lib/characters';
import { EmptyState, SectionHeader } from '@/components/common/primitives';
import CharacterAppearanceList from './CharacterAppearanceList';
import type {
  CharacterAppearanceCreateAppearanceType,
  CharacterResponse,
  CharacterTimelineResponse,
} from '@/lib/api/generated/model';
import type { ChapterSummary } from '@/types';

interface CharacterTimelineProps {
  novelId: number;
}

const MAX_CHAPTER_PAGES = 20;

/**
 * 「TA 的经历」区：单人物视角的出场排线。后端 timeline 路由只回 appearances
 * （milestones/relationship_changes 恒空，预检实测），故只做出场时间线，不做占位假区块。
 * 冷启动诚实空态 + 手动补录（章节 + 类型 + 说明）；MCP track_appearance 自动追踪一期不接。
 */
export default function CharacterTimeline({ novelId }: CharacterTimelineProps) {
  const [characters, setCharacters] = useState<CharacterResponse[]>([]);
  const [charactersLoading, setCharactersLoading] = useState(true);
  const [error, setError] = useState('');
  const controllerRef = useRef<AbortController | null>(null);

  const [selectedId, setSelectedId] = useState('');
  const [timeline, setTimeline] = useState<CharacterTimelineResponse | null>(null);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [timelineError, setTimelineError] = useState('');
  // 重试通过递增计数器重触发时间线加载效应。
  const [timelineAttempt, setTimelineAttempt] = useState(0);
  const timelineControllerRef = useRef<AbortController | null>(null);

  const loadCharacters = useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setCharactersLoading(true);
    setError('');
    try {
      const items = await charactersApi.list(novelId, controller.signal);
      if (!controller.signal.aborted) {
        setCharacters(items);
        setSelectedId((current) => current || (items.length > 0 ? String(items[0].id) : ''));
      }
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : '读取人物档案失败');
    } finally {
      if (!controller.signal.aborted) setCharactersLoading(false);
    }
  }, [novelId]);

  useEffect(() => {
    void loadCharacters();
    return () => controllerRef.current?.abort();
  }, [loadCharacters]);

  useEffect(() => {
    if (!selectedId) {
      setTimeline(null);
      return;
    }
    const controller = new AbortController();
    timelineControllerRef.current?.abort();
    timelineControllerRef.current = controller;
    setTimelineLoading(true);
    setTimelineError('');
    charactersApi.timeline(Number(selectedId), controller.signal).then((value) => {
      if (!controller.signal.aborted) setTimeline(value);
    }).catch((failure) => {
      if (!controller.signal.aborted) setTimelineError(failure instanceof Error ? failure.message : '读取经历失败');
    }).finally(() => {
      if (!controller.signal.aborted) setTimelineLoading(false);
    });
    return () => controller.abort();
  }, [selectedId, timelineAttempt]);

  // 补录出场弹窗：章节列表按需分页取全（pageSize 上限 100）。
  const [backfillOpen, setBackfillOpen] = useState(false);
  const [chapters, setChapters] = useState<ChapterSummary[]>([]);
  const [chaptersLoading, setChaptersLoading] = useState(false);
  const [chaptersError, setChaptersError] = useState('');
  const [chapterId, setChapterId] = useState('');
  const [appearanceType, setAppearanceType] = useState<CharacterAppearanceCreateAppearanceType>('supporting');
  const [description, setDescription] = useState('');
  const [saving, setSaving] = useState(false);
  const [submitError, setSubmitError] = useState('');

  const loadChapters = async () => {
    setChaptersLoading(true);
    setChaptersError('');
    try {
      const collected: ChapterSummary[] = [];
      let page = 1;
      for (;;) {
        const result = await api.getChapterSummaries(novelId, { page, pageSize: 100 });
        collected.push(...result.items);
        if (!result.has_more || page >= MAX_CHAPTER_PAGES) break;
        page += 1;
      }
      setChapters(collected);
    } catch (failure) {
      setChaptersError(failure instanceof Error ? failure.message : '读取章节列表失败');
    } finally {
      setChaptersLoading(false);
    }
  };

  const openBackfill = () => {
    setError('');
    setChapterId('');
    setDescription('');
    setSubmitError('');
    setBackfillOpen(true);
    if (chapters.length === 0) void loadChapters();
  };

  const submitBackfill = async () => {
    if (!selectedId || !chapterId || saving) return;
    setSaving(true);
    setSubmitError('');
    try {
      await charactersApi.createAppearance({
        character_id: Number(selectedId),
        chapter_id: Number(chapterId),
        appearance_type: appearanceType,
        description: description.trim() ? description.trim() : null,
      });
      setBackfillOpen(false);
      await charactersApi.timeline(Number(selectedId)).then((value) => setTimeline(value));
    } catch (failure) {
      setSubmitError(failure instanceof Error ? failure.message : '补录出场失败');
    } finally {
      setSaving(false);
    }
  };

  const selectedCharacter = characters.find((character) => String(character.id) === selectedId);

  return <Card elevation={0} sx={{ border: 1, borderColor: 'divider', mt: 3 }}>
    <CardContent sx={{ p: { xs: 2, sm: 3 } }}>
      <SectionHeader title="TA 的经历" />
      <Typography variant="body2" color="text.secondary">按章节排线的人物经历：出场即经历，谁在哪一章做了什么。</Typography>
      {error && <Alert severity="error" sx={{ mt: 2 }} action={<Button color="inherit" onClick={() => void loadCharacters()}>重试</Button>}>{error}</Alert>}
      {charactersLoading && <Typography role="status" sx={{ mt: 2 }}>正在读取人物档案…</Typography>}
      {!charactersLoading && !error && characters.length === 0 && <Box sx={{ mt: 2 }}>
        <EmptyState title="还没有人物档案。" hint="先在上方人物档案区创建人物，再来记录 TA 的经历。" />
      </Box>}
      {characters.length > 0 && <Box sx={{ mt: 2 }}>
        <TextField
          select
          label="人物"
          value={selectedId}
          onChange={(event) => setSelectedId(event.target.value)}
          sx={{ minWidth: 220 }}
        >
          {characters.map((character) => <MenuItem key={character.id} value={String(character.id)}>{character.name}</MenuItem>)}
        </TextField>
        {selectedCharacter && <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mt: 2 }}>
          <Typography variant="subtitle2">{selectedCharacter.name} 的出场排线</Typography>
          <Button size="small" onClick={openBackfill}>补录出场</Button>
        </Stack>}
        {timelineLoading && <Typography role="status" sx={{ mt: 1 }}>正在读取经历…</Typography>}
        {timelineError && <Alert severity="error" sx={{ mt: 1 }} action={<Button color="inherit" onClick={() => setTimelineAttempt((value) => value + 1)}>重试</Button>}>{timelineError}</Alert>}
        {selectedId && !timelineLoading && !timelineError && timeline && timeline.appearances.length > 0 && (
          <CharacterAppearanceList appearances={timeline.appearances} />
        )}
        {selectedId && !timelineLoading && !timelineError && timeline && timeline.appearances.length === 0 && <Box sx={{ mt: 1 }}>
          <EmptyState
            title="还没有出场记录。"
            hint="出场即经历：手动补录第一笔，时间线会随之展开。"
            action={<Button color="inherit" onClick={openBackfill}>补录出场</Button>}
          />
        </Box>}
      </Box>}
      <Dialog open={backfillOpen} onClose={() => { if (!saving) setBackfillOpen(false); }} maxWidth="md" fullWidth>
        <DialogTitle>补录出场</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            {submitError && <Alert severity="error">{submitError}</Alert>}
            {chaptersError && <Alert severity="error" action={<Button color="inherit" onClick={() => void loadChapters()}>重试</Button>}>{chaptersError}</Alert>}
            <TextField
              select
              label="章节"
              value={chapterId}
              onChange={(event) => setChapterId(event.target.value)}
              disabled={chaptersLoading}
              helperText={chaptersLoading && chapters.length === 0 ? '正在读取章节列表…' : ' '}
            >
              {chapters.map((chapter) => (
                <MenuItem key={chapter.id} value={String(chapter.id)}>第 {chapter.chapter_number} 章 {chapter.title}</MenuItem>
              ))}
            </TextField>
            <TextField
              select
              label="出场类型"
              value={appearanceType}
              onChange={(event) => setAppearanceType(event.target.value as CharacterAppearanceCreateAppearanceType)}
            >
              <MenuItem value="main">主场</MenuItem>
              <MenuItem value="supporting">出场</MenuItem>
              <MenuItem value="mentioned">提及</MenuItem>
            </TextField>
            <TextField
              label="说明"
              multiline
              rows={2}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              helperText="这位人物在这一章做了什么、发生了什么变化。"
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button disabled={saving} onClick={() => setBackfillOpen(false)}>取消</Button>
          <Button variant="contained" disabled={!chapterId || saving} onClick={() => void submitBackfill()}>
            {saving ? '保存中…' : '补录'}
          </Button>
        </DialogActions>
      </Dialog>
    </CardContent>
  </Card>;
}
