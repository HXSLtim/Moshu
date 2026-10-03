'use client';

import { Box, Container, Stack, Typography } from '@mui/material';
import AutoStoriesRoundedIcon from '@mui/icons-material/AutoStoriesRounded';
import ColorModeToggle from './ColorModeToggle';

export default function AuthFrame({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default', display: 'grid', placeItems: 'center', py: 4 }}>
      <Container maxWidth="sm">
        <Stack alignItems="center" sx={{ mb: 3 }}>
          <Stack direction="row" alignItems="center" gap={1}>
            <AutoStoriesRoundedIcon color="primary" />
            <Typography sx={{ fontWeight: 800, letterSpacing: '.14em' }}>墨枢</Typography>
          </Stack>
          <Typography component="h1" variant="h4" sx={{ mt: 2, fontWeight: 700, textAlign: 'center' }}>{title}</Typography>
          <Typography color="text.secondary" sx={{ mt: 1, textAlign: 'center' }}>{description}</Typography>
        </Stack>
        <Box sx={{ position: 'absolute', top: 16, right: 16 }}><ColorModeToggle /></Box>
        {children}
      </Container>
    </Box>
  );
}

