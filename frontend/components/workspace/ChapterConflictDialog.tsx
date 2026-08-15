'use client';

import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Grid,
  TextField,
  Typography,
} from '@mui/material';
import type { Chapter } from '@/types';
import type { ChapterSaveConflict } from '@/hooks/useChapterSave';

export type ConflictAction = 'accept' | 'overwrite' | 'copy';

interface ChapterConflictDialogProps {
  open: boolean;
  conflict: ChapterSaveConflict | null;
  serverChapter: Chapter | null;
  loadingServer: boolean;
  actionLoading: ConflictAction | null;
  onAcceptServer: () => void;
  onOverwriteServer: () => void;
  onCopyToNewChapter: () => void;
  onClose: () => void;
}

function VersionPanel({
  title,
  content,
  version,
}: {
  title: string;
  content: string;
  version?: number;
}) {
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, minWidth: 0 }}>
      <Box sx={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 1 }}>
        <Typography variant="subtitle2" noWrap>
          {title}
        </Typography>
        {typeof version === 'number' && (
          <Typography variant="caption" color="text.secondary" flexShrink={0}>
            v{version}
          </Typography>
        )}
      </Box>
      <TextField
        fullWidth
        multiline
        minRows={12}
        maxRows={20}
        value={content}
        slotProps={{
          input: {
            readOnly: true,
          },
        }}
        sx={{
          '& .MuiInputBase-input': {
            fontSize: '0.85rem',
            lineHeight: 1.6,
            fontFamily: 'inherit',
          },
        }}
      />
    </Box>
  );
}

export default function ChapterConflictDialog({
  open,
  conflict,
  serverChapter,
  loadingServer,
  actionLoading,
  onAcceptServer,
  onOverwriteServer,
  onCopyToNewChapter,
  onClose,
}: ChapterConflictDialogProps) {
  const localTitle = conflict?.snapshot.title || '';
  const localContent = conflict?.snapshot.content || '';

  return (
    <Dialog open={open} onClose={onClose} maxWidth="lg" fullWidth>
      <DialogTitle>章节保存冲突</DialogTitle>
      <DialogContent>
        <Alert severity="warning" sx={{ mb: 2 }}>
          你的版本与服务端版本不一致。请选择保留其中一份，或把本地版本另存为新章节。
        </Alert>

        <Grid container spacing={2}>
          <Grid item xs={12} md={6}>
            <VersionPanel
              title={`我的版本：${localTitle}`}
              content={localContent}
              version={conflict?.snapshot.expectedVersion}
            />
          </Grid>
          <Grid item xs={12} md={6}>
            {loadingServer ? (
              <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
                <CircularProgress size={28} />
              </Box>
            ) : serverChapter ? (
              <VersionPanel
                title={`服务端版本：${serverChapter.title}`}
                content={serverChapter.content}
                version={serverChapter.version}
              />
            ) : (
              <Alert severity="info">暂时无法加载服务端版本，可关闭后重试。</Alert>
            )}
          </Grid>
        </Grid>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>关闭</Button>
        <Button
          color="inherit"
          disabled={actionLoading !== null || !serverChapter}
          onClick={onAcceptServer}
        >
          {actionLoading === 'accept' ? '处理中...' : '放弃我的版本'}
        </Button>
        <Button
          variant="outlined"
          disabled={actionLoading !== null}
          onClick={onCopyToNewChapter}
        >
          {actionLoading === 'copy' ? '创建中...' : '另存为新章节'}
        </Button>
        <Button
          variant="contained"
          color="warning"
          disabled={actionLoading !== null || !serverChapter}
          onClick={onOverwriteServer}
        >
          {actionLoading === 'overwrite' ? '覆盖中...' : '用我的版本覆盖'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
