'use client';

import { Suspense, useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Alert, Box, Button, Typography } from '@mui/material';
import AppFrame from '@/components/layout/AppFrame';
import WorldviewEditor from '@/components/novel/WorldviewEditor';
import StoryBibleManager from '@/components/novel/StoryBibleManager';
import CharacterManager from '@/components/novel/CharacterManager';
import CharacterRelationshipEditor from '@/components/novel/CharacterRelationshipEditor';
import CharacterTimeline from '@/components/novel/CharacterTimeline';
import { api, ApiError } from '@/lib/api';
import type { Novel } from '@/types';


function StoryBibleSession() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const novelId = Number(searchParams.get('novel'));
  const [novel, setNovel] = useState<Novel | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  // 人物档案变更计数：Manager 存档后递增，关系区/经历区以此为依赖重取，下拉不再等刷新。
  const [charactersVersion, setCharactersVersion] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setNovel(null);
    setError('');
    void api.getNovel(novelId, { signal: controller.signal }).then((value) => {
      if (!controller.signal.aborted) setNovel(value);
    }).catch((failure) => {
      if (controller.signal.aborted) return;
      // 与工作台一致：登录态失效时说明原因并送回登录页，不直出接口报错。
      if (failure instanceof ApiError && (failure.status === 401 || failure.status === 403)) {
        setError('登录状态已失效，请重新登录');
        setTimeout(() => router.push('/'), 2000);
      } else {
        setError(failure instanceof Error ? failure.message : '读取小说失败');
      }
    });
    return () => controller.abort();
  }, [novelId, attempt, router]);
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
        : <><WorldviewEditor key={novelId} novel={novel} /><StoryBibleManager novelId={novelId} /><CharacterManager novelId={novelId} onSaved={() => setCharactersVersion((value) => value + 1)} /><CharacterRelationshipEditor novelId={novelId} refreshKey={charactersVersion} /><CharacterTimeline novelId={novelId} refreshKey={charactersVersion} /></>}
    </Box>
  </AppFrame>;
}

// 静态导出要求 useSearchParams 页面套 Suspense 边界。
export default function StoryBiblePage() {
  return <Suspense fallback={null}><StoryBibleSession /></Suspense>;
}
