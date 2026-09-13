'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  TextField,
  Button,
  Card,
  CardContent,
  Alert,
} from '@mui/material';
import AuthFrame from '@/components/layout/AuthFrame';
import { api } from '@/lib/api';

export default function RegisterPage() {
  const router = useRouter();
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (password !== confirmPassword) {
      setError('两次输入的密码不一致');
      return;
    }

    if (password.length < 6) {
      setError('密码长度至少为6个字符');
      return;
    }

    setLoading(true);

    try {
      const data = await api.register({ username, email, password });
      localStorage.setItem('token', data.access_token);
      localStorage.setItem('user', JSON.stringify(data.user));
      router.push('/dashboard');
    } catch (err) {
      setError(err instanceof Error ? err.message : '注册失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthFrame title="创建你的写作空间" description="注册后只要起一个名字，就能开始一本新小说。">
        <Card sx={{ mt: 3, width: '100%' }}>
          <CardContent>
            <form onSubmit={handleRegister}>
              {error && (
                <Alert severity="error" sx={{ mb: 2 }}>
                  {error}
                </Alert>
              )}
              <TextField
                fullWidth
                label="用户名"
                placeholder="3-50 个字符"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                margin="normal"
                required
                autoFocus
                helperText="3-50个字符"
              />
              <TextField
                fullWidth
                label="邮箱"
                placeholder="用于找回账号"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                margin="normal"
                required
              />
              <TextField
                fullWidth
                label="密码"
                placeholder="至少 6 个字符"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                margin="normal"
                required
                helperText="至少6个字符"
              />
              <TextField
                fullWidth
                label="确认密码"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                margin="normal"
                required
              />
              <Button
                fullWidth
                variant="contained"
                type="submit"
                sx={{ mt: 2 }}
                disabled={loading}
              >
                {loading ? '正在创建…' : '创建账号并开始'}
              </Button>
              <Button
                fullWidth
                variant="text"
                onClick={() => router.push('/')}
                sx={{ mt: 1 }}
              >
                已有账号，去登录
              </Button>
            </form>
          </CardContent>
        </Card>
    </AuthFrame>
  );
}
