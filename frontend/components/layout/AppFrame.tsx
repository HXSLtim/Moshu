'use client';

import Link from 'next/link';
import { Box, Button, Container, Stack, Typography } from '@mui/material';
import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded';
import AutoStoriesRoundedIcon from '@mui/icons-material/AutoStoriesRounded';
import ColorModeToggle from './ColorModeToggle';

interface AppFrameProps {
  eyebrow?: string;
  title: string;
  description?: string;
  backHref?: string;
  backLabel?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
  maxWidth?: 'md' | 'lg' | 'xl';
}

/** 非工作台页面统一的产品壳层：品牌、位置、页面目标和主要动作保持一致。 */
export default function AppFrame({
  eyebrow = 'NAI 写作系统', title, description, backHref, backLabel = '返回', actions, children, maxWidth = 'lg',
}: AppFrameProps) {
  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default' }}>
      <Box component="header" sx={{ borderBottom: 1, borderColor: 'divider', bgcolor: 'background.paper' }}>
        <Container maxWidth={maxWidth} sx={{ py: 1.5 }}>
          <Stack direction="row" alignItems="center" justifyContent="space-between" gap={2}>
            <Stack direction="row" alignItems="center" gap={1.5} minWidth={0}>
              <Button component={Link} href="/dashboard" color="inherit" sx={{ minWidth: 0, px: 0, fontWeight: 800, letterSpacing: '.12em' }} startIcon={<AutoStoriesRoundedIcon color="primary" />}>
                NAI
              </Button>
              {backHref && <Button component={Link} href={backHref} size="small" color="inherit" startIcon={<ArrowBackRoundedIcon />} sx={{ display: { xs: 'none', sm: 'inline-flex' } }}>{backLabel}</Button>}
            </Stack>
            <Stack direction="row" alignItems="center" gap={0.5} flexShrink={0}>
              {actions}
              <ColorModeToggle />
            </Stack>
          </Stack>
        </Container>
      </Box>
      <Container maxWidth={maxWidth} sx={{ py: { xs: 3, md: 5 } }}>
        <Box sx={{ mb: { xs: 3, md: 4 } }}>
          <Typography variant="overline" color="primary" sx={{ letterSpacing: '.12em', fontWeight: 700 }}>{eyebrow}</Typography>
          <Typography component="h1" variant="h3" sx={{ mt: 0.5, fontWeight: 700, letterSpacing: '-.02em', fontSize: { xs: '2rem', md: '2.75rem' } }}>{title}</Typography>
          {description && <Typography color="text.secondary" sx={{ mt: 1, maxWidth: 720, fontSize: { xs: '0.95rem', md: '1.05rem' } }}>{description}</Typography>}
        </Box>
        {children}
      </Container>
    </Box>
  );
}

