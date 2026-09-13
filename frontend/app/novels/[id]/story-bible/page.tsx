'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { Alert, Box, Button, Typography } from '@mui/material';
import AppFrame from '@/components/layout/AppFrame';
import WorldviewEditor from '@/components/novel/WorldviewEditor';
import StoryBibleManager from '@/components/novel/StoryBibleManager';
import { api } from '@/lib/api';
import type { Novel } from '@/types';


export default function StoryBiblePage() {
  const params = useParams();
  const novelId = Number(params.id);
  const [novel, setNovel] = useState<Novel | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setNovel(null);
    setError('');
    void api.getNovel(novelId, { signal: controller.signal }).then((value) => {
      if (!controller.signal.aborted) setNovel(value);
    }).catch((failure) => {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : '读取小说失败');
    });
    return () => controller.abort();
  }, [novelId, attempt]);
  return <AppFrame
    eyebrow="设定"
    title="设定账本"
    description={novel ? `${novel.title} · 世界观、人物事实与剧情线索。AI 只会读取这里已确认的内容。` : '世界观、人物事实与剧情线索。'}
    backHref={`/novels/${novelId}`}
    backLabel="返回项目"
    maxWidth="md"
  >
    <Box>
      {error ? <Alert severity="error" action={<Button color="inherit" onClick={() => setAttempt((value) => value + 1)}>重试</Button>}>{error}</Alert>
        : !novel ? <Typography role="status">正在读取项目…</Typography>
        : <><WorldviewEditor key={novelId} novel={novel} /><StoryBibleManager novelId={novelId} /></>}
    </Box>
  </AppFrame>;
}
