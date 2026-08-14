'use client';

import { useState, useCallback } from 'react';
import {
  Card,
  CardContent,
  Typography,
  TextField,
  Button,
  Box,
  Divider,
  List,
  ListItem,
  Chip,
  Alert,
  CircularProgress,
  Link,
  Accordion,
  AccordionSummary,
  AccordionDetails,
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import HistoryIcon from '@mui/icons-material/History';
import { api } from '@/lib/api';

interface ResearchResult {
  title: string;
  summary: string;
  source: string;
  url?: string | null;
  metadata?: Record<string, any>;
}

interface ResearchAssistantProps {
  novelId: number;
  onError: (error: string) => void;
}

export default function ResearchAssistant({
  novelId,
  onError,
}: ResearchAssistantProps) {
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<ResearchResult[]>([]);
  const [searchHistory, setSearchHistory] = useState<string[]>([]);

  const handleSearch = useCallback(async () => {
    if (!query.trim()) {
      onError('请输入搜索关键词');
      return;
    }

    setLoading(true);
    try {
      const response = await api.researchSearch({
        query: query.trim(),
        novel_id: novelId,
        category: 'general',
      });

      setResults(response.results);
      
      // 添加到搜索历史
      setSearchHistory(prev => {
        const newHistory = [query.trim(), ...prev.filter(q => q !== query.trim())];
        return newHistory.slice(0, 10); // 保留最近10次搜索
      });
    } catch (err) {
      onError(err instanceof Error ? err.message : '资料检索失败');
    } finally {
      setLoading(false);
    }
  }, [query, novelId, onError]);

  const handleHistoryClick = useCallback((historyQuery: string) => {
    setQuery(historyQuery);
  }, []);

  const handleKeyPress = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSearch();
    }
  }, [handleSearch]);

  const getSourceColor = (source: string) => {
    const lowerSource = source.toLowerCase();
    if (lowerSource.includes('wikipedia') || lowerSource.includes('百科')) return 'info';
    if (lowerSource.includes('academic') || lowerSource.includes('学术')) return 'success';
    if (lowerSource.includes('news') || lowerSource.includes('新闻')) return 'warning';
    return 'default';
  };

  return (
    <Card sx={{ mb: 2 }}>
      <CardContent>
        <Typography variant="subtitle2" gutterBottom>
          资料检索
        </Typography>
        <Divider sx={{ my: 1 }} />

        {/* 搜索输入 */}
        <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
          <TextField
            fullWidth
            size="small"
            label="搜索历史背景、专业知识..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="例如：唐朝服饰、量子物理、古代建筑..."
            disabled={loading}
          />
          <Button
            variant="contained"
            startIcon={loading ? <CircularProgress size={16} color="inherit" /> : <SearchIcon />}
            onClick={handleSearch}
            disabled={loading || !query.trim()}
            sx={{ 
              minWidth: 80,
              height: 40, // 匹配TextField的高度
              whiteSpace: 'nowrap',
              flexShrink: 0,
            }}
          >
            {loading ? '搜索中' : '搜索'}
          </Button>
        </Box>

        {/* 搜索历史 */}
        {searchHistory.length > 0 && (
          <Box sx={{ mb: 2 }}>
            <Typography variant="caption" color="text.secondary" gutterBottom>
              最近搜索:
            </Typography>
            <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
              {searchHistory.slice(0, 5).map((historyQuery, idx) => (
                <Chip
                  key={idx}
                  label={historyQuery}
                  size="small"
                  variant="outlined"
                  icon={<HistoryIcon />}
                  onClick={() => handleHistoryClick(historyQuery)}
                  sx={{ cursor: 'pointer' }}
                />
              ))}
            </Box>
          </Box>
        )}

        {/* 搜索结果 */}
        {results.length > 0 ? (
          <Box>
            <Typography variant="caption" color="text.secondary" gutterBottom>
              找到 {results.length} 条相关资料:
            </Typography>
            
            <List>
              {results.map((result, idx) => (
                <ListItem key={idx} sx={{ px: 0, py: 1 }}>
                  <Accordion sx={{ width: '100%' }} elevation={0}>
                    <AccordionSummary
                      expandIcon={<ExpandMoreIcon />}
                      sx={{
                        px: 1,
                        '& .MuiAccordionSummary-content': {
                          flexDirection: 'column',
                          alignItems: 'flex-start',
                        },
                      }}
                    >
                      <Box sx={{ width: '100%' }}>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                          <Typography variant="body2" fontWeight="medium">
                            {result.title}
                          </Typography>
                          {result.url && (
                            <Link
                              href={result.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <OpenInNewIcon fontSize="small" />
                            </Link>
                          )}
                        </Box>
                        
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                          <Chip
                            label={result.source}
                            size="small"
                            color={getSourceColor(result.source) as any}
                            variant="outlined"
                          />
                          {result.metadata?.category && (
                            <Chip
                              label={result.metadata.category}
                              size="small"
                              variant="outlined"
                            />
                          )}
                        </Box>
                      </Box>
                    </AccordionSummary>
                    
                    <AccordionDetails sx={{ px: 1, pt: 0 }}>
                      <Typography
                        variant="body2"
                        color="text.secondary"
                        sx={{ lineHeight: 1.6 }}
                      >
                        {result.summary}
                      </Typography>
                      
                      {result.metadata && Object.keys(result.metadata).length > 0 && (
                        <Box sx={{ mt: 2 }}>
                          <Typography variant="caption" color="text.secondary" gutterBottom>
                            附加信息:
                          </Typography>
                          <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                            {Object.entries(result.metadata)
                              .filter(([key]) => key !== 'category')
                              .slice(0, 3)
                              .map(([key, value]) => (
                                <Chip
                                  key={key}
                                  label={`${key}: ${value}`}
                                  size="small"
                                  variant="outlined"
                                  sx={{ fontSize: '0.7rem', height: 20 }}
                                />
                              ))}
                          </Box>
                        </Box>
                      )}
                    </AccordionDetails>
                  </Accordion>
                </ListItem>
              ))}
            </List>
          </Box>
        ) : !loading && query ? (
          <Alert severity="info">
            <Typography variant="body2">
              未找到相关资料，请尝试其他关键词。
            </Typography>
          </Alert>
        ) : (
          <Box>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              搜索历史背景、专业知识、文化资料等，为您的写作提供准确的参考信息。
            </Typography>
            
            <Alert severity="info">
              <Typography variant="body2">
                <strong>搜索建议：</strong>
                <br />• 历史背景：朝代、事件、人物
                <br />• 专业知识：科学、技术、医学
                <br />• 文化资料：习俗、建筑、服饰
                <br />• 地理信息：城市、地形、气候
              </Typography>
            </Alert>
          </Box>
        )}
      </CardContent>
    </Card>
  );
}
