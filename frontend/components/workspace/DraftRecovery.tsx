'use client';

import { useState } from 'react';
import { Accordion, AccordionDetails, AccordionSummary, Alert, Button, Stack, Typography } from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import type { RecoverableDraft } from '@/lib/chapterDrafts';

const reasons = { legacy: '旧格式草稿，无法核验作者与作品身份', different_account: '其他账号的草稿，请切回原账号导出', different_lifecycle: '作品或章节已删除重建，旧稿仅供恢复参考', older: '与服务端版本不一致的旧草稿' };
export default function DraftRecovery({ drafts }: { drafts: RecoverableDraft[] }) {
  const [error, setError] = useState('');
  if (!drafts.length) return null;
  const download = (item: RecoverableDraft) => {
    if (item.reason === 'different_account') return;
    try {
      const url = URL.createObjectURL(new Blob([JSON.stringify(item.draft, null, 2)], { type: 'application/json;charset=utf-8' }));
      const link = document.createElement('a');
      link.href = url; link.download = `墨枢-恢复草稿-${item.draft.novelId}-${item.draft.chapterId}.json`;
      link.click();
      const revoke = URL.revokeObjectURL.bind(URL);
      setTimeout(() => revoke(url), 1000);
      setError('');
    } catch { setError('导出失败，备份仍保留在本机，请重试。'); }
  };
  return <Accordion disableGutters sx={{ mb: 2 }}>
    <AccordionSummary expandIcon={<ExpandMoreIcon />}><Typography>有 {drafts.length} 份本机草稿等待核对</Typography></AccordionSummary>
    <AccordionDetails><Stack spacing={1.5}>
      <Typography variant="body2">这些草稿未载入正文。可先导出保留，核对内容后手动恢复；导出不会清除本机备份。</Typography>
      {error && <Alert severity="warning">{error}</Alert>}
      {drafts.map((item) => <Stack key={item.storageKey} spacing={0.5}>
        <Typography variant="body2">{reasons[item.reason]}</Typography>
        {item.reason !== 'different_account' && <Typography variant="caption">{item.draft.title} · {item.draft.savedAt} · 版本 {item.draft.version}</Typography>}
        <Button size="small" disabled={item.reason === 'different_account'} onClick={() => download(item)}>导出恢复草稿</Button>
      </Stack>)}
    </Stack></AccordionDetails>
  </Accordion>;
}
