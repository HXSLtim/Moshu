'use client';

import IconButton from '@mui/material/IconButton';
import Tooltip from '@mui/material/Tooltip';
import DarkModeIcon from '@mui/icons-material/DarkMode';
import LightModeIcon from '@mui/icons-material/LightMode';
import { useColorMode } from '@/hooks/useColorMode';

interface ColorModeToggleProps {
  /** 继承图标颜色，便于放在 AppBar 或普通页头。 */
  inheritColor?: boolean;
}

export default function ColorModeToggle({
  inheritColor = false,
}: ColorModeToggleProps) {
  const { isDark, toggleColorMode } = useColorMode();
  const label = isDark ? '切换到浅色模式' : '切换到深色模式';

  return (
    <Tooltip title={label}>
      <IconButton
        color={inheritColor ? 'inherit' : 'default'}
        aria-label={label}
        onClick={toggleColorMode}
      >
        {isDark ? <LightModeIcon /> : <DarkModeIcon />}
      </IconButton>
    </Tooltip>
  );
}
