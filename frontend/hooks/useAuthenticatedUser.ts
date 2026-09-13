'use client';

import { useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import type { User } from '@/types';

/** 服务端核验当前令牌所属作者；跨标签登录变化先撤销旧身份。 */
export function useAuthenticatedUser(): User | null {
  const [user, setUser] = useState<User | null>(null);
  const sequence = useRef(0);
  useEffect(() => {
    let active = true;
    let previousToken: string | null | undefined;
    const refresh = () => {
      let token: string | null = null;
      try { token = localStorage.getItem('token'); } catch { /* 无存储权限时保持未核验。 */ }
      if (token === previousToken) return;
      previousToken = token;
      const request = ++sequence.current;
      setUser(null);
      if (!token) return;
      void api.getCurrentUser().then((value) => {
        if (active && sequence.current === request) setUser(value);
      }).catch(() => { if (active && sequence.current === request) setUser(null); });
    };
    refresh();
    window.addEventListener('storage', refresh);
    window.addEventListener('focus', refresh);
    return () => { active = false; sequence.current += 1; window.removeEventListener('storage', refresh); window.removeEventListener('focus', refresh); };
  }, []);
  return user;
}
