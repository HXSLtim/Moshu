'use client';

import { useCallback, useDeferredValue, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Collapse,
  Divider,
  IconButton,
  LinearProgress,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import PersonIcon from '@mui/icons-material/Person';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import TrendingDownIcon from '@mui/icons-material/TrendingDown';
import { countTextUnits } from '@/lib/textStats';
import { charactersApi } from '@/lib/characters';
import { EmptyState } from '@/components/common/primitives';
import type { Novel } from '@/types';
import type { CharacterResponse } from '@/lib/api/generated/model';

type StatsSource = 'worldview' | 'character';

/** 偏好键按书隔离；无记录一律回世界观正则（旧书零回退）。 */
const sourceStorageKey = (novelId: number) => `nai.character-stats.source.${novelId}`;
const hintDismissedKey = (novelId: number) => `nai.character-stats.source-hint-dismissed.${novelId}`;

interface CharacterStat {
  name: string;
  count: number;
  percentage: number;
  trend?: 'up' | 'down' | 'stable';
}

interface CharacterStatsProps {
  novel: Novel | null;
  currentContent: string;
  previousContent?: string;
  /** 是否有选中章节：false 时统计没有对象，给引导而非 0/0 空转。 */
  hasChapter?: boolean;
}

export default function CharacterStats({
  novel,
  currentContent,
  previousContent = '',
  hasChapter = true,
}: CharacterStatsProps) {
  const novelId = novel?.id;
  const [expanded, setExpanded] = useState(false);
  const deferredContent = useDeferredValue(currentContent);

  // 名单来源：默认世界观正则；偏好按 novelId 存 localStorage，读完存储才渲染引导防闪。
  const [source, setSource] = useState<StatsSource>('worldview');
  const [sourceReady, setSourceReady] = useState(false);
  const [hintDismissed, setHintDismissed] = useState(true);
  const [characters, setCharacters] = useState<CharacterResponse[] | null>(null);
  const [charactersError, setCharactersError] = useState('');

  useEffect(() => {
    if (novelId == null) return;
    const stored = window.localStorage.getItem(sourceStorageKey(novelId));
    if (stored === 'character' || stored === 'worldview') setSource(stored);
    setHintDismissed(window.localStorage.getItem(hintDismissedKey(novelId)) === '1');
    setSourceReady(true);
  }, [novelId]);

  const loadCharacters = useCallback(async () => {
    if (novelId == null) return;
    setCharactersError('');
    try {
      const items = await charactersApi.list(novelId);
      setCharacters(items);
    } catch (failure) {
      setCharactersError(failure instanceof Error ? failure.message : '读取人物档案失败');
    }
  }, [novelId]);

  useEffect(() => {
    void loadCharacters();
  }, [loadCharacters]);

  const changeSource = (next: StatsSource) => {
    if (!next) return;
    setSource(next);
    if (novelId != null) window.localStorage.setItem(sourceStorageKey(novelId), next);
  };

  const dismissHint = () => {
    setHintDismissed(true);
    if (novelId != null) window.localStorage.setItem(hintDismissedKey(novelId), '1');
  };

  // 从世界观中提取角色名单
  const extractCharacterNames = (worldviewText: string): string[] => {
    if (!worldviewText) return [];

    const mainCharHeader = '【主要角色】';
    const outlineHeader = '【章节大纲】';
    const plotHeader = '【剧情线索】';

    const start = worldviewText.indexOf(mainCharHeader);
    if (start === -1) return [];

    let end = worldviewText.length;
    const outlineIndex = worldviewText.indexOf(outlineHeader, start + mainCharHeader.length);
    if (outlineIndex !== -1) {
      end = Math.min(end, outlineIndex);
    }
    const plotIndex = worldviewText.indexOf(plotHeader, start + mainCharHeader.length);
    if (plotIndex !== -1) {
      end = Math.min(end, plotIndex);
    }

    const section = worldviewText.slice(start + mainCharHeader.length, end);
    const lines = section
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);

    const namesSet = new Set<string>();
    const separators = ['：', ':', '-', '—', '——'];

    for (const line of lines) {
      let namePart = line;
      for (const sep of separators) {
        const idx = line.indexOf(sep);
        if (idx > 0) {
          namePart = line.slice(0, idx);
          break;
        }
      }
      const cleaned = namePart.replace(/^[-?·\s]+/, '').trim();
      if (cleaned && cleaned.length >= 2 && cleaned.length <= 10) {
        namesSet.add(cleaned);
      }
    }

    return Array.from(namesSet);
  };

  // 统计角色在文本中的出现次数
  const calculateCharacterStats = (names: string[], text: string, prevText?: string): CharacterStat[] => {
    if (names.length === 0 || !text) return [];

    const stats: CharacterStat[] = [];
    const totalLength = text.length;

    for (const name of names) {
      const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const regex = new RegExp(escaped, 'g');
      const matches = text.match(regex);
      const count = matches ? matches.length : 0;
      const percentage = totalLength > 0 ? (count / totalLength) * 1000 : 0; // 每千字出现次数

      let trend: 'up' | 'down' | 'stable' = 'stable';
      if (prevText) {
        const prevMatches = prevText.match(regex);
        const prevCount = prevMatches ? prevMatches.length : 0;
        const prevPercentage = prevText.length > 0 ? (prevCount / prevText.length) * 1000 : 0;

        if (percentage > prevPercentage + 0.5) trend = 'up';
        else if (percentage < prevPercentage - 0.5) trend = 'down';
      }

      stats.push({ name, count, percentage, trend });
    }

    // 按出现次数排序
    stats.sort((a, b) => b.count - a.count);
    return stats;
  };

  // 名单按来源取：档案源直接用档案名，正则源维持世界观解析。
  const characterNames = useMemo(() => {
    if (source === 'character') return characters?.map((character) => character.name) ?? [];
    return novel?.worldview ? extractCharacterNames(novel.worldview) : [];
  }, [source, characters, novel?.worldview]);

  // 正文扫描使用延迟值，避免输入期间阻塞编辑器的高优先级更新。
  const characterStats = useMemo(
    () => calculateCharacterStats(characterNames, deferredContent, previousContent),
    [characterNames, deferredContent, previousContent],
  );

  // 获取活跃角色（出现次数 > 0）
  const activeCharacters = characterStats.filter(stat => stat.count > 0);
  const inactiveCharacters = characterStats.filter(stat => stat.count === 0);

  // 获取趋势图标
  const getTrendIcon = (trend?: string) => {
    switch (trend) {
      case 'up':
        return <TrendingUpIcon color="success" fontSize="small" />;
      case 'down':
        return <TrendingDownIcon color="error" fontSize="small" />;
      default:
        return null;
    }
  };

  const maxCount = Math.max(...characterStats.map(s => s.count), 1);

  if (!novel) return null;

  const sourceSwitch = (
    <ToggleButtonGroup
      size="small"
      exclusive
      value={source}
      onChange={(_, value) => changeSource(value as StatsSource)}
      aria-label="统计名单来源"
    >
      <ToggleButton value="worldview">世界观</ToggleButton>
      <ToggleButton value="character">人物档案</ToggleButton>
    </ToggleButtonGroup>
  );

  // 正则源读档案只为一次性引导，读取失败静默（不打扰）；档案源失败必须诚实展示。
  const characterSourceError = source === 'character' && charactersError ? (
    <Alert severity="error" sx={{ mt: 1 }} action={<Button color="inherit" onClick={() => void loadCharacters()}>重试</Button>}>{charactersError}</Alert>
  ) : null;

  // 名单为空：按来源分流引导，禁占位假数据。
  if (characterNames.length === 0) {
    return (
      <Card sx={{ mb: 2 }}>
        <CardContent>
          <Typography variant="subtitle2" gutterBottom>
            角色统计
          </Typography>
          <Divider sx={{ my: 1 }} />
          {sourceSwitch}
          <Box sx={{ mt: 2 }}>
            {source === 'character' && characters !== null && (
              <EmptyState
                title="还没有人物档案。"
                hint="去设定账本的人物档案区创建；建立后统计会按档案名单计数。"
              />
            )}
            {source === 'character' && characters === null && !charactersError && (
              <Typography role="status">正在读取人物档案…</Typography>
            )}
            {source === 'worldview' && (
              <EmptyState
                title="还没有从世界观找到角色名单。"
                hint="在世界观加【主要角色】小节，每行一位（如「张三：主角，年轻的剑客」）；也可切到人物档案源。"
              />
            )}
          </Box>
          {characterSourceError}
        </CardContent>
      </Card>
    );
  }

  // 未选章节时统计没有对象：给最近路径引导，不渲染 0/0 空转。
  if (!hasChapter) {
    return (
      <Card sx={{ mb: 2 }}>
        <CardContent>
          <Typography variant="subtitle2" gutterBottom>
            角色统计
          </Typography>
          <Divider sx={{ my: 1 }} />
          {sourceSwitch}
          <Box sx={{ mt: 2 }}>
            <EmptyState
              title="还没有选中的章节。"
              hint="统计按当前章节正文计数；先在左侧选一章，这里就会显示各角色在本章的出场情况。"
            />
          </Box>
          {characterSourceError}
        </CardContent>
      </Card>
    );
  }

  // 有档案且还在用正则源：一次性引导切源，知道了后按书记忆不再出现。
  const showHint = sourceReady && source === 'worldview' && !hintDismissed && (characters?.length ?? 0) > 0;

  return (
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
          <Typography variant="subtitle2">角色统计</Typography>
          <IconButton
            size="small"
            onClick={() => setExpanded(!expanded)}
            aria-label={expanded ? '收起角色列表' : '展开角色列表'}
            aria-expanded={expanded}
          >
            {expanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
          </IconButton>
        </Box>
        <Divider sx={{ my: 1 }} />

        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 1, mb: 1 }}>
          {sourceSwitch}
          <Typography variant="caption" color="text.secondary">
            名单来源：{source === 'character' ? '人物档案' : '世界观'}
          </Typography>
        </Box>
        {showHint && <Box sx={{ mb: 2 }}>
          <EmptyState
            title={`已建档 ${characters?.length ?? 0} 名人物。`}
            hint="想让统计按档案名单计数，就切到「人物档案」源；本提示只出现这一次。"
            action={
              <Box sx={{ display: 'flex', gap: 0.5 }}>
                <Button size="small" color="inherit" onClick={() => changeSource('character')}>切换</Button>
                <Button size="small" color="inherit" onClick={dismissHint}>知道了</Button>
              </Box>
            }
          />
        </Box>}
        {characterSourceError}

        {/* 概览信息 */}
        <Box sx={{ mb: 2 }}>
          <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
            <Chip
              label={`活跃角色: ${activeCharacters.length}`}
              size="small"
              color="success"
              variant="outlined"
            />
            <Chip
              label={`未出现: ${inactiveCharacters.length}`}
              size="small"
              color="default"
              variant="outlined"
            />
          </Box>
          <Typography variant="caption" color="text.secondary">
            当前章节共 {countTextUnits(currentContent).toLocaleString()} 字
            {deferredContent !== currentContent ? '（统计更新中）' : ''}
          </Typography>
        </Box>

        {/* 活跃角色列表 */}
        {activeCharacters.length > 0 && (
          <Box sx={{ mb: 2 }}>
            <Typography variant="caption" color="text.secondary" gutterBottom>
              活跃角色:
            </Typography>
            <List dense>
              {activeCharacters.slice(0, expanded ? activeCharacters.length : 3).map((stat) => (
                <ListItem key={stat.name} sx={{ px: 0, py: 0.5 }}>
                  <ListItemIcon sx={{ minWidth: 32 }}>
                    <PersonIcon color="primary" fontSize="small" />
                  </ListItemIcon>
                  <ListItemText
                    disableTypography
                    primary={
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <Typography variant="body2" fontWeight="medium">
                          {stat.name}
                        </Typography>
                        {getTrendIcon(stat.trend)}
                        {/* 次数是属性不是状态：灰描边，红只留真错误；强弱交给下方进度条长度。 */}
                        <Chip
                          label={`${stat.count}次`}
                          size="small"
                          color="default"
                          variant="outlined"
                        />
                      </Box>
                    }
                    secondary={
                      <Box sx={{ mt: 0.5 }}>
                        <LinearProgress
                          variant="determinate"
                          value={(stat.count / maxCount) * 100}
                          sx={{ height: 4, borderRadius: 2 }}
                          color="primary"
                        />
                        <Typography variant="caption" color="text.secondary">
                          每千字出现 {stat.percentage.toFixed(1)} 次
                        </Typography>
                      </Box>
                    }
                  />
                </ListItem>
              ))}
            </List>

            {!expanded && activeCharacters.length > 3 && (
              <Typography
                variant="caption"
                color="primary"
                sx={{ cursor: 'pointer' }}
                onClick={() => setExpanded(true)}
              >
                还有 {activeCharacters.length - 3} 个角色...
              </Typography>
            )}
          </Box>
        )}

        {/* 详细信息 */}
        <Collapse in={expanded}>
          {inactiveCharacters.length > 0 && (
            <Box>
              <Typography variant="caption" color="text.secondary" gutterBottom>
                未出现角色:
              </Typography>
              <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mb: 2 }}>
                {inactiveCharacters.map((stat) => (
                  <Chip
                    key={stat.name}
                    label={stat.name}
                    size="small"
                    variant="outlined"
                    color="default"
                  />
                ))}
              </Box>
            </Box>
          )}

        </Collapse>
      </CardContent>
    </Card>
  );
}
