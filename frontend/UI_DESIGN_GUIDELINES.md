# UI/UX 设计规范文档

## 目录
- [设计理念](#设计理念)
- [设计系统](#设计系统)
  - [颜色体系](#颜色体系)
  - [字体系统](#字体系统)
  - [间距系统](#间距系统)
  - [阴影系统](#阴影系统)
  - [圆角规范](#圆角规范)
- [组件设计规范](#组件设计规范)
  - [按钮](#按钮)
  - [卡片](#卡片)
  - [输入框](#输入框)
  - [信息提示](#信息提示)
- [交互动效](#交互动效)
- [实施指南](#实施指南)
- [未来优化方向](#未来优化方向)

---

## 设计理念

### 「纸墨」设计哲学

本项目的UI设计以传统中国书法文化为灵感，将**宣纸**、**墨砚**、**毛笔**等元素融入现代数字界面设计中，打造具有东方美学特色的AI写作工具。

**核心设计原则：**

1. **内容为王**：界面以内容为中心，减少视觉干扰，让作者专注创作
2. **简约克制**：去除多余装饰，保留必要元素，遵循"少即是多"原则
3. **层次分明**：通过颜色、间距、阴影建立清晰的信息层级
4. **温润亲和**：避免冷硬的科技感，营造温暖、亲和的写作氛围
5. **可扩展性**：建立统一的设计系统，便于团队协作和功能扩展

**设计关键词：**
- 简约 (Simplicity)
- 温润 (Warmth)
- 专注 (Focus)
- 优雅 (Elegance)
- 文化 (Culture)

---

## 设计系统

### 颜色体系

#### 主色调
- **主色** (`primary`): `#006C52` - 低饱和绿，如松烟墨，沉稳内敛
- **次色** (`secondary`): `#5F5F5F` - 中性灰，平衡整体视觉
- **背景色** (`background`): `#F9F7F2` - 宣纸白，温暖纸色
- **文字色** (`text`): `#1D1C1A` - 墨黑，如浓墨书写

#### 功能色
- **成功色** (`success`): `#2E7D32` - 深绿，如墨迹干透
- **警告色** (`warning`): `#E65100` - 琥珀橙，醒目但不刺眼
- **错误色** (`error`): `#C62828` - 深红，如朱砂批改
- **信息色** (`info`): `#01579B` - 藏青，如靛蓝墨水

#### 层级色
```typescript
// 背景层级
background.default: '#F9F7F2'  // 页面背景
background.paper: '#FFFFFF'    // 卡片背景
background.subtle: '#F5F3EC'   // 柔和背景

// 边框层级
border.light: '#E8E6E0'  // 细分隔线
border.main: '#D6D3C8'   // 主分隔线
border.dark: '#C7C2B9'   // 强分隔线
```

#### 深色「夜墨」模式

浅色是纸，深色是夜墨。深色模式不是纯黑，而是保留宣纸暖意的低亮度色板：

```typescript
background.default: '#1B1B1B'  // 纯黑上浮 5%
background.paper: '#242424'    // 卡片背景
text.primary: '#E2E0DB'        // 米白，保留暖色
text.secondary: '#9E9E9E'      // 次级灰
primary.main: '#4EC9A1'        // 降低亮度的松烟绿
divider: '#494944'             // 弱化分隔
```

主题切换入口使用 `components/layout/ColorModeToggle.tsx`；应用启动时读取用户保存选择，没有保存选择时跟随 `prefers-color-scheme`。

### 字体系统

#### 字体栈
```typescript
fontFamily: [
  '-apple-system',           // macOS系统字体
  'BlinkMacSystemFont',      // Chrome/Edge macOS
  '"Segoe UI"',              // Windows系统字体
  'Roboto',                  // Android系统字体
  '"Noto Sans SC"',          // 思源黑体（中文）
  'sans-serif',
].join(',')
```

#### 字体层级

| 样式 | 大小 | 字重 | 行高 | 用途 |
|------|------|------|------|------|
| `h1` | 40px (2.5rem) | 600 | 1.2 | 页面主标题 |
| `h2` | 32px (2rem) | 600 | 1.3 | 页面副标题 |
| `h3` | 28px (1.75rem) | 600 | 1.3 | 区块标题 |
| `h4` | 24px (1.5rem) | 500 | 1.4 | 卡片标题 |
| `h5` | 20px (1.25rem) | 500 | 1.4 | 小标题 |
| `h6` | 18px (1.125rem) | 500 | 1.4 | 标签标题 |
| `subtitle1` | 16px (1rem) | 500 | 1.5 | 强调文字 |
| `body1` | 16px (1rem) | 400 | 1.75 | 正文（阅读优化）|
| `body2` | 14px (0.875rem) | 400 | 1.6 | 次要文字 |
| `caption` | 12px (0.75rem) | 400 | 1.4 | 辅助信息 |
| `overline` | 12px (0.75rem) | 600 | 1.4 | 标签文字 |

**阅读优化**：
- 正文字体大小：16px（适合长时间阅读）
- 行高：1.75（最佳可读性）
- 字间距：0.02em（优化中文排版）

### 间距系统

基于8px的网格系统：

```typescript
spacing(factor) = 0.5rem * factor  // 8px * factor
```

**常用间距：**
```typescript
theme.spacing(1)   // 8px   - 最小间距
theme.spacing(2)   // 16px  - 小组件内间距
theme.spacing(3)   // 24px  - 卡片内间距
theme.spacing(4)   // 32px  - 区块间距
theme.spacing(6)   // 48px  - 大区块间距
theme.spacing(8)   // 64px  - 页面级间距
```

### 阴影系统

使用Material Design的Elevation系统，提供24级阴影：

```typescript
// 常用阴影示例
shadows[1]  // Card默认阴影
theme.shadows[2]  // Card悬停阴影
theme.shadows[4]  // Dialog阴影
theme.shadows[8]  // AppBar阴影
```

### 圆角规范

- **按钮**：8px
- **输入框**：8px
- **标签 (Chip)**：16px
- **卡片 (Card)**：12px
- **纸张 (Paper)**：12px
- **对话框**：12px
- **提示信息 (Alert)**：8px
- **进度条**：4px

---

## 组件设计规范

### 按钮

#### 基础规范
- **最小高度**：40px（small: 32px, large: 48px）
- **内边距**：8px 16px（左右各16px，上下各8px）
- **圆角**：8px
- **字体权重**：500（Medium）
- **不自动大写**：`textTransform: 'none'`

#### 视觉层次

1. **主要按钮（Contained）**
   - 使用场景：主要操作、CTA按钮
   - 视觉特征：填充主色，白色文字
   - 悬停效果：上移1px，添加阴影

2. **次要按钮（Outlined）**
   - 使用场景：次要操作、取消按钮
   - 视觉特征：描边1.5px，透明背景
   - 悬停效果：背景色不变，上移1px

3. **文本按钮（Text）**
   - 使用场景：链接、不重要的操作
   - 视觉特征：无背景，有文字颜色

#### 交互反馈
- 悬停：`transform: translateY(-1px)` + 阴影变化
- 过渡：`transition: all 0.2s ease-in-out`

### 卡片

#### 基础规范
- **圆角**：12px
- **边框**：1px 浅灰描边
- **阴影**：`shadows[1]`（默认）
- **背景**：白色
- **内边距**：16px 或 24px（根据内容密度）

#### 交互行为
- **默认状态**：静态阴影
- **悬停状态**：上移2px + `shadows[2]`
- **过渡动画**：`transition: all 0.2s ease-in-out`

#### 使用场景
- 小说列表项
- 统计信息卡片
- 功能模块卡片
- 内容展示区块

### 输入框

#### 基础规范
- **高度**：56px（遵循Material Design标准）
- **圆角**：8px
- **边框**：1px 灰色调
- **内边距**：16px

#### 状态样式
1. **默认状态**
   - 边框色：`border.main` (#D6D3C8)
   - 背景色：白色

2. **悬停状态**
   - 边框色：主色 (`primary.main`)
   - 边框加粗：2px

3. **聚焦状态**
   - 边框色：主色 (`primary.main`)
   - 边框加粗：2px

#### 标签样式
- 字体大小：12px
- 颜色：次级文字色
- 在聚焦时上移

### 信息提示

#### 成功提示（Success）
```typescript
{
  borderColor: '#2E7D32',           // 成功色
  backgroundColor: '#E8F5E9',       // 容器色
  color: '#2E7D32',                 // 文字色
  border: '1px solid',
  borderRadius: '8px',
}
```

#### 错误提示（Error）
```typescript
{
  borderColor: '#C62828',           // 错误色
  backgroundColor: '#FFEBEE',       // 容器色
  color: '#C62828',                 // 文字色
  border: '1px solid',
  borderRadius: '8px',
}
```

#### 警告提示（Warning）
```typescript
{
  borderColor: '#E65100',           // 警告色
  backgroundColor: '#FFF3E0',       // 容器色
  color: '#E65100',                 // 文字色
  border: '1px solid',
  borderRadius: '8px',
}
```

#### 信息提示（Info）
```typescript
{
  borderColor: '#01579B',           // 信息色
  backgroundColor: '#E1F5FE',       // 容器色
  color: '#01579B',                 // 文字色
  border: '1px solid',
  borderRadius: '8px',
}
```

---

## 交互动效

### 缓动函数
```css
/* 标准缓动 */
transition: all 0.2s ease-in-out;

/* 快速缓动 */
transition: all 0.15s ease-out;

/* 缓慢缓动 */
transition: all 0.3s ease-in-out;
```

### 常用动画效果

#### 1. 悬停上移
```css
transform: translateY(-1px);  /* 按钮 */
transform: translateY(-2px);  /* 卡片 */
transition: all 0.2s ease-in-out;
```

#### 2. 阴影变化
```css
box-shadow: 0 2px 8px rgba(0,0,0,0.08);  /* 默认 */
box-shadow: 0 4px 12px rgba(0,0,0,0.12); /* 悬停 */
```

#### 3. 颜色过渡
```css
transition: background-color 0.2s ease-in-out,
            border-color 0.2s ease-in-out,
            color 0.2s ease-in-out;
```

---

## 实施指南

### 快速开始

1. **应用主题**

```typescript
// app/layout.tsx
import { createAppTheme } from '@/theme/theme';

const theme = createAppTheme(mode);
<ThemeProvider theme={theme}>
```

2. **使用间距系统**

```typescript
// 使用主题间距
<Box sx={{ mt: theme.spacing(2), p: 3 }}>

// 或使用函数
<Box sx={{ mt: (theme) => theme.spacing(2) }}>
```

3. **使用颜色变量**

```typescript
<Box sx={{
  color: 'primary.main',          // 主色
  bgcolor: 'background.paper',    // 卡片背景
  borderColor: 'border.light',    // 边框色
}}>
```

### 开发规范

#### 组件开发

1. **优先使用MUI组件**：不重复造轮子，利用MUI的成熟组件库
2. **遵循样式规范**：使用主题配置的颜色、间距、圆角、阴影
3. **添加交互动效**：重要交互需要添加悬停效果和过渡动画
4. **响应式设计**：所有组件需要在移动端和桌面端都能良好展示
5. **可访问性**：遵循WCAG标准，提供足够的颜色对比度

#### 样式组织

```typescript
// ✅ 推荐：使用sx prop
<Button sx={{
  borderRadius: 1,        // theme.shape.borderRadius
  boxShadow: 1,           // theme.shadows[1]
  '&:hover': {
    transform: 'translateY(-1px)',
    boxShadow: 2,
  }
}}>

// ✅ 推荐：主题变量
const useStyles = (theme: Theme) => ({
  root: {
    padding: theme.spacing(3),
    transition: theme.transitions.create(['box-shadow']),
  }
});

// ❌ 避免：硬编码样式
<Button style={{
  padding: '24px',
  borderRadius: '8px',
  boxShadow: '0 2px 8px rgba(0,0,0,0.08)'
}}>
```

### 性能优化

1. **主题memo化**
```typescript
const theme = useMemo(() => createAppTheme(mode), [mode]);
```

2. **减少重渲染**
```typescript
// 使用sx配置而非内联样式
// 内联样式每次渲染都会创建新对象

// ✅ 推荐
<Box sx={{ mt: 2, p: 3 }}>

// ❌ 避免
<Box style={{ marginTop: '16px', padding: '24px' }}>
```

3. **按需加载MUI组件**
```typescript
// ✅ 推荐：按需导入
import Button from '@mui/material/Button';

// ❌ 避免：全量导入
import { Button, Card, TextField } from '@mui/material';
```

---

## 未来优化方向

### 优先级：高

1. **页面转场动画**
   - 使用Next.js App Router的parallel routes和interception实现
   - 在路由切换时添加缓动动画

2. **AI生成进度可视化**
   - 为Agent工作流添加实时动画
   - 显示生成进度和状态

3. **写作工作区优化**
   - 沉浸式写作模式（全屏、隐藏干扰）
   - 实时保存动画反馈
   - 字数统计动画

4. **响应式优化**
   - 移动端布局适配
   - 触摸友好的交互设计
   - 移动端导航优化

### 优先级：中

5. **微交互完善**
   - 按钮点击反馈
   - 卡片悬停效果
   - 表单验证动画
   - 加载状态动画

6. **图标系统**
   - 建立一致的图标风格
   - 统一图标大小和风格
   - 添加图标配色规范

7. **数据可视化**
   - 统计图表设计规范
   - 角色关系图谱可视化UX
   - 时间线视图设计

8. **可访问性优化**
   - 键盘导航支持
   - 屏幕阅读器友好
   - 高对比度模式

### 优先级：低

9. **高级动画**
   - Framer Motion集成
   - 复杂交互动画
   - 手势交互

10. **国际化适配**
    - RTL布局支持
    - 不同语言排版优化

---

## 设计资源

### 参考工具

1. **Figma** - UI设计工具
2. **Material Design Guidelines** - MUI设计规范
3. **Coolors** - 配色工具
4. **Font Pair** - 字体搭配

### 学习资源

- [Material Design System](https://m3.material.io/)
- [MUI官方文档](https://mui.com/material-ui/getting-started/)
- [CSS Tricks - UI设计](https://css-tricks.com/)
- [NNGroup UX研究](https://www.nngroup.com/)

---

**文档版本**：v1.0
**创建日期**：2025-11-19
**维护者**：UI/UX设计师 & 前端开发团队
**更新频率**：每个Sprint回顾时更新
