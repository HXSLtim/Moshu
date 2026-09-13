'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Box,
  TextField,
  Button,
  Typography,
  Card,
  CardContent,
  Alert,
  Chip,
  Divider,
  Accordion,
  AccordionSummary,
  AccordionDetails,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import InfoIcon from '@mui/icons-material/Info';
import AuthFrame from '@/components/layout/AuthFrame';
import { api } from '@/lib/api';

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<'unknown' | 'testing' | 'success' | 'failed'>('unknown');

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const data = await api.login({ username, password });
      localStorage.setItem('token', data.access_token);
      localStorage.setItem('user', JSON.stringify(data.user));
      router.push('/dashboard');
    } catch (err) {
      console.error('登录错误详情:', err);
      
      let errorMessage = '登录失败';
      if (err instanceof Error) {
        if (err.message.includes('fetch')) {
          errorMessage = '无法连接到服务器，请检查网络连接和服务器状态';
        } else if (err.message.includes('401')) {
          errorMessage = '用户名或密码错误';
        } else if (err.message.includes('CORS')) {
          errorMessage = '跨域访问被阻止，请联系管理员';
        } else {
          errorMessage = err.message;
        }
      }
      
      setError(errorMessage);
    } finally {
      setLoading(false);
    }
  };

  // 测试API连接
  const testConnection = async () => {
    setConnectionStatus('testing');
    setError('');
    
    try {
      const apiBase = process.env.NEXT_PUBLIC_API_BASE || 'http://127.0.0.1:8000/api';
      const healthUrl = apiBase.replace('/api', '') + '/api/health';
      
      console.log('[DEBUG] 测试API连接:', healthUrl);
      
      const response = await fetch(healthUrl, {
        method: 'GET',
        headers: {
          'Accept': 'application/json',
        },
      });
      
      if (response.ok) {
        const data = await response.json();
        console.log('[DEBUG] 连接成功:', data);
        setConnectionStatus('success');
      } else {
        console.error('[DEBUG] 连接失败:', response.status, response.statusText);
        setConnectionStatus('failed');
        setError(`连接测试失败: ${response.status} ${response.statusText}`);
      }
    } catch (err) {
      console.error('🚨 连接测试错误:', err);
      setConnectionStatus('failed');
      setError(`连接测试失败: ${err instanceof Error ? err.message : '未知错误'}`);
    }
  };

  // 获取调试信息
  const getDebugInfo = () => {
    const apiBase = process.env.NEXT_PUBLIC_API_BASE || 'http://127.0.0.1:8000/api';
    const userAgent = typeof navigator !== 'undefined' ? navigator.userAgent : 'Unknown';
    const currentUrl = typeof window !== 'undefined' ? window.location.href : 'Unknown';
    
    return {
      apiBase,
      userAgent,
      currentUrl,
      timestamp: new Date().toLocaleString(),
    };
  };

  return (
    <AuthFrame title="欢迎回到 Nai" description="把想法变成章节，AI 负责协助，你保留最后决定权。">
        <Card sx={{ mt: 3, width: '100%' }}>
          <CardContent>
            <form onSubmit={handleLogin}>
              {error && (
                <Alert severity="error" sx={{ mb: 2 }}>
                  {error}
                </Alert>
              )}
              <TextField
                fullWidth
                label="用户名"
                placeholder="输入你的用户名"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                margin="normal"
                required
                autoFocus
              />
              <TextField
                fullWidth
                label="密码"
                placeholder="输入密码"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                margin="normal"
                required
              />
              <Button
                fullWidth
                variant="contained"
                type="submit"
                sx={{ mt: 2 }}
                disabled={loading || connectionStatus === 'testing'}
              >
                {loading ? '正在进入…' : '进入写作空间'}
              </Button>
              
              {/* 连接测试按钮 */}
              <Button
                fullWidth
                variant="outlined"
                onClick={testConnection}
                disabled={connectionStatus === 'testing'}
                sx={{ 
                  mt: 1,
                  color: connectionStatus === 'success' ? 'success.main' : 
                         connectionStatus === 'failed' ? 'error.main' : 'primary.main'
                }}
              >
                {connectionStatus === 'testing' ? '检查连接中…' : 
                 connectionStatus === 'success' ? '服务连接正常' :
                 connectionStatus === 'failed' ? '服务连接失败' : '检查服务连接'}
              </Button>
              
              <Button
                fullWidth
                variant="text"
                onClick={() => router.push('/register')}
                sx={{ mt: 1 }}
              >
                创建新账号
              </Button>
            </form>
          </CardContent>
        </Card>

        {/* 调试信息面板 */}
        {process.env.NEXT_PUBLIC_DEBUG === 'true' && (
          <Card sx={{ mt: 2, width: '100%' }}>
            <Accordion>
              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <InfoIcon color="info" />
                  <Typography variant="body2">调试信息</Typography>
                  <Chip label="移动端调试" size="small" color="info" />
                </Box>
              </AccordionSummary>
              <AccordionDetails>
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                  <Typography variant="caption" color="text.secondary">
                    <strong>API地址:</strong> {getDebugInfo().apiBase}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    <strong>当前URL:</strong> {getDebugInfo().currentUrl}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    <strong>用户代理:</strong> {getDebugInfo().userAgent}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    <strong>时间戳:</strong> {getDebugInfo().timestamp}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    <strong>连接状态:</strong> 
                    <Chip 
                      label={connectionStatus === 'success' ? '正常' : 
                             connectionStatus === 'failed' ? '失败' : 
                             connectionStatus === 'testing' ? '测试中' : '未测试'}
                      size="small"
                      color={connectionStatus === 'success' ? 'success' : 
                             connectionStatus === 'failed' ? 'error' : 'default'}
                      sx={{ ml: 1 }}
                    />
                  </Typography>
                  
                  <Divider sx={{ my: 1 }} />
                  
                  <Typography variant="body2" fontWeight="600" color="warning.main">
                    连接问题排查步骤：
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    1. 点击“测试API连接”按钮检查后端连接
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    2. 确保手机和电脑在同一WiFi网络
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    3. 检查电脑防火墙是否阻止8000端口
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    4. 确认后端服务正在运行 (python start_mobile.py)
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    5. 手动访问API文档: {getDebugInfo().apiBase.replace('/api', '')}/docs
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    6. 检查浏览器控制台的网络错误信息
                  </Typography>
                </Box>
              </AccordionDetails>
            </Accordion>
          </Card>
        )}
    </AuthFrame>
  );
}
