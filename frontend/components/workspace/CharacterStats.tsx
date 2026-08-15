'use client';

import { useState, useMemo, useDeferredValue } from 'react';
import {
  Card,
  CardContent,
  Typography,
  Box,
  Divider,
  List,
  ListItem,
  ListItemText,
  ListItemIcon,
  Chip,
  LinearProgress,
  Alert,
  Collapse,
  IconButton,
} from '@mui/material';
import PersonIcon from '@mui/icons-material/Person';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import TrendingDownIcon from '@mui/icons-material/TrendingDown';
import { countTextUnits } from '@/lib/textStats';
import type { Novel } from '@/types';

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
}

export default function CharacterStats({
  novel,
  currentContent,
  previousContent = '',
}: CharacterStatsProps) {
  const [expanded, setExpanded] = useState(false);
  const deferredContent = useDeferredValue(currentContent);

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

  const characterNames = useMemo(
    () => (novel?.worldview ? extractCharacterNames(novel.worldview) : []),
    [novel?.worldview],
  );

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

  // 获取活跃度颜色
  const getActivityColor = (count: number, maxCount: number) => {
    if (count === 0) return 'default';
    const ratio = count / maxCount;
    if (ratio >= 0.7) return 'error';
    if (ratio >= 0.4) return 'warning';
    if (ratio >= 0.2) return 'info';
    return 'success';
  };

  const maxCount = Math.max(...characterStats.map(s => s.count), 1);

  if (!novel?.worldview) {
    return (
      <Card sx={{ mb: 2 }}>
        <CardContent>
          <Typography variant="subtitle2" gutterBottom>
            角色统计
          </Typography>
          <Divider sx={{ my: 1 }} />
          <Typography variant="body2" color="text.secondary">
            请在小说设置中添加世界观信息，包含【主要角色】部分。
          </Typography>
        </CardContent>
      </Card>
    );
  }

  if (characterStats.length === 0) {
    return (
      <Card sx={{ mb: 2 }}>
        <CardContent>
          <Typography variant="subtitle2" gutterBottom>
            角色统计
          </Typography>
          <Divider sx={{ my: 1 }} />
          <Alert severity="info">
            <Typography variant="body2">
              未在世界观中找到【主要角色】部分。请按以下格式添加：
              <br />
              【主要角色】
              <br />
              张三：主角，年轻的剑客
              <br />
              李四：反派，邪恶的法师
            </Typography>
          </Alert>
        </CardContent>
      </Card>
    );
  }

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
          >
            {expanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
          </IconButton>
        </Box>
        <Divider sx={{ my: 1 }} />

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
                        <Chip
                          label={`${stat.count}次`}
                          size="small"
                          color={getActivityColor(stat.count, maxCount) as any}
                        />
                      </Box>
                    }
                    secondary={
                      <Box sx={{ mt: 0.5 }}>
                        <LinearProgress
                          variant="determinate"
                          value={(stat.count / maxCount) * 100}
                          sx={{ height: 4, borderRadius: 2 }}
                          color={getActivityColor(stat.count, maxCount) as any}
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

          {activeCharacters.length > 0 && (
            <Alert severity="info">
              <Typography variant="body2">
                <strong>写作建议：</strong>
                {activeCharacters.length === 1 && '当前章节主要围绕一个角色展开，考虑增加其他角色的互动。'}
                {activeCharacters.length >= 2 && activeCharacters.length <= 3 && '角色分布较为均衡，适合推进剧情发展。'}
                {activeCharacters.length > 3 && '角色较多，注意保持每个角色的独特性和必要性。'}
                {inactiveCharacters.length > 0 && `还有 ${inactiveCharacters.length} 个角色未在当前章节出现。`}
              </Typography>
            </Alert>
          )}
        </Collapse>
      </CardContent>
    </Card>
  );
}
