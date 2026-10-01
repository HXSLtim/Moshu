# 功能扩展任务清单

> 状态：历史设想，已归档。表内工期、人员、接口和代码片段未与当前实现同步，不作为当前能力或交付计划；演进边界以 `ARCHITECTURE.md` 为准。

AI小说创作系统的高级功能扩展，提升系统能力和用户体验。

## 🎯 扩展功能概览

| 功能模块 | 优先级 | 预计工期 | 负责人 |
|---------|--------|---------|--------|
| 用户认证和权限管理 | P0（高） | 1周 | 后端开发C |
| 章节管理CRUD | P0（高） | 1周 | 后端开发C |
| 导出功能（EPUB/PDF） | P1（中） | 2周 | 后端开发D |
| 角色关系图谱可视化 | P1（中） | 1周 | 前端开发B |
| LLM响应缓存系统 | P1（中） | 1周 | 后端开发D |
| 实时协作编辑 | P2（低） | 2周 | 全栈开发E |
| 多语言支持（i18n） | P2（低） | 1周 | 前端开发A/B |
| 语音转文字输入 | P3（可选） | 1周 | 前端开发B |

---

## 👥 人员分配方案

### **团队规模**：3人（2后端 + 1全栈）

| 角色 | 人数 | 职责 |
|-----|-----|-----|
| **后端开发C** | 1人 | 用户认证、章节管理、权限系统 |
| **后端开发D** | 1人 | 导出功能、缓存优化、性能调优 |
| **全栈开发E** | 1人 | 实时协作、WebSocket、前后端联调 |

---

## 📋 任务详细分解

### 🔐 P0优先级：核心基础功能

#### **任务组1：用户认证和权限管理**（后端开发C，1周）

**背景**：当前系统缺少用户系统，需要实现用户注册、登录和权限控制。

**技术选型**：
- JWT（JSON Web Token）- 无状态认证
- bcrypt - 密码加密
- FastAPI Dependency Injection - 权限验证

**任务1.1 用户模型和数据库**（1天）
- [ ] 设计User数据模型（PostgreSQL）
  ```python
  class User(Base):
      id: int
      username: str
      email: str
      hashed_password: str
      created_at: datetime
      is_active: bool
      role: str  # "user" | "admin"
  ```
- [ ] 创建用户表migration
- [ ] 实现密码加密/验证工具

**文件**：
- `backend/app/models/database.py`
- `backend/app/models/user.py`
- `backend/alembic/versions/xxx_create_users_table.py`

**任务1.2 认证API接口**（2天）
- [ ] POST `/api/auth/register` - 用户注册
- [ ] POST `/api/auth/login` - 用户登录（返回JWT）
- [ ] POST `/api/auth/refresh` - 刷新Token
- [ ] GET `/api/auth/me` - 获取当前用户信息
- [ ] POST `/api/auth/logout` - 退出登录

**文件**：
- `backend/app/api/routes/auth.py`
- `backend/app/services/auth_service.py`

**任务1.3 权限依赖注入**（1天）
- [ ] 实现`get_current_user`依赖
- [ ] 实现`require_admin`依赖
- [ ] 为现有API添加权限保护

**代码示例**：
```python
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

async def get_current_user(token: str = Depends(oauth2_scheme)):
    """获取当前登录用户"""
    payload = jwt.decode(token, SECRET_KEY)
    user = await db.get_user(payload["user_id"])
    if not user:
        raise HTTPException(401, "未授权")
    return user

# 使用示例
@router.post("/novels")
async def create_novel(
    novel: NovelCreate,
    user: User = Depends(get_current_user)
):
    # 只有登录用户才能创建小说
    pass
```

**任务1.4 前端集成**（1天）
- [ ] 实现登录/注册页面（配合前端开发A）
- [ ] 实现Token存储（localStorage）
- [ ] 实现自动Token刷新
- [ ] 添加请求拦截器（自动附加Token）

**验收标准**：
- ✅ 用户可以注册和登录
- ✅ JWT Token正确签发和验证
- ✅ 所有API接口有权限保护
- ✅ 前端请求自动携带Token

---

#### **任务组2：章节管理CRUD**（后端开发C，1周）

**背景**：需要完整的章节增删改查功能，支持小说的章节组织。

**任务2.1 章节数据模型**（1天）
- [ ] 设计Chapter数据模型
  ```python
  class Chapter(Base):
      id: int
      novel_id: int
      chapter_number: int
      title: str
      content: str  # 章节正文
      word_count: int
      status: str  # "draft" | "published"
      created_at: datetime
      updated_at: datetime
  ```
- [ ] 创建章节表migration
- [ ] 建立Novel与Chapter的关联关系

**文件**：
- `backend/app/models/chapter.py`
- `backend/alembic/versions/xxx_create_chapters_table.py`

**任务2.2 章节API接口**（2天）
- [ ] POST `/api/chapters` - 创建章节
- [ ] GET `/api/chapters/{id}` - 获取章节详情
- [ ] PUT `/api/chapters/{id}` - 更新章节
- [ ] DELETE `/api/chapters/{id}` - 删除章节
- [ ] GET `/api/novels/{novel_id}/chapters` - 获取小说的所有章节
- [ ] POST `/api/chapters/{id}/publish` - 发布章节
- [ ] POST `/api/chapters/batch-create` - 批量创建章节

**文件**：
- `backend/app/api/routes/chapters.py`
- `backend/app/services/chapter_service.py`

**任务2.3 章节内容索引**（1天）
- [ ] 章节保存时自动索引到Qdrant
- [ ] 章节删除时清理Qdrant索引
- [ ] 支持章节内容搜索

**任务2.4 章节版本历史**（1天，可选）
- [ ] 创建ChapterHistory表记录修改历史
- [ ] 实现版本回滚功能
- [ ] 版本对比功能

**验收标准**：
- ✅ 支持完整的章节CRUD
- ✅ 章节自动索引到向量数据库
- ✅ 章节内容可搜索
- ✅ 支持草稿和发布状态

---

### 📦 P1优先级：增强功能

#### **任务组3：导出功能（EPUB/PDF）**（后端开发D，2周）

**背景**：用户需要将小说导出为标准电子书格式，方便分享和阅读。

**技术选型**：
- **EPUB生成**：ebooklib (Python库)
- **PDF生成**：WeasyPrint或ReportLab
- **异步任务**：Celery + Redis（处理长时间导出）

**任务3.1 EPUB导出**（3天）
- [ ] 安装和配置ebooklib
- [ ] 实现EPUB文件生成逻辑
  - 封面页
  - 目录（TOC）
  - 章节内容
  - 元数据（作者、标题、ISBN）
- [ ] 实现流式下载

**代码示例**：
```python
from ebooklib import epub

def generate_epub(novel_id: int) -> bytes:
    """生成EPUB文件"""
    novel = db.get_novel(novel_id)
    chapters = db.get_chapters(novel_id)

    book = epub.EpubBook()
    book.set_title(novel.title)
    book.set_language('zh')

    # 添加章节
    epub_chapters = []
    for ch in chapters:
        c = epub.EpubHtml(
            title=ch.title,
            file_name=f'chap_{ch.chapter_number}.xhtml',
            lang='zh'
        )
        c.content = f'<h1>{ch.title}</h1><p>{ch.content}</p>'
        book.add_item(c)
        epub_chapters.append(c)

    # 生成目录
    book.toc = tuple(epub_chapters)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # 输出
    epub.write_epub('output.epub', book, {})
    return open('output.epub', 'rb').read()
```

**任务3.2 PDF导出**（3天）
- [ ] 安装和配置WeasyPrint
- [ ] 设计PDF模板（HTML+CSS）
- [ ] 实现PDF生成逻辑
- [ ] 添加页眉页脚、页码
- [ ] 支持自定义封面

**任务3.3 异步任务系统**（2天）
- [ ] 配置Celery + Redis
- [ ] 创建导出任务
  ```python
  @celery_app.task
  def export_novel_async(novel_id: int, format: str):
      if format == 'epub':
          return generate_epub(novel_id)
      elif format == 'pdf':
          return generate_pdf(novel_id)
  ```
- [ ] 实现任务状态查询
- [ ] 下载完成后发送通知

**任务3.4 API接口**（1天）
- [ ] POST `/api/novels/{id}/export` - 发起导出任务
  ```json
  {
    "format": "epub",  // "epub" | "pdf" | "docx"
    "options": {
      "include_cover": true,
      "include_toc": true
    }
  }
  ```
- [ ] GET `/api/exports/{task_id}/status` - 查询导出状态
- [ ] GET `/api/exports/{task_id}/download` - 下载文件

**任务3.5 前端集成**（1天）
- [ ] 导出配置界面
- [ ] 进度条展示
- [ ] 下载按钮

**验收标准**：
- ✅ 支持EPUB、PDF导出
- ✅ 导出任务异步处理
- ✅ 生成的文件格式正确
- ✅ 支持自定义封面和样式

---

#### **任务组4：LLM响应缓存系统**（后端开发D，1周）

**背景**：LLM API调用费用高，需要缓存重复请求，降低成本。

**技术选型**：
- Redis - 缓存存储
- 哈希算法 - 生成缓存Key（基于prompt+参数）

**任务4.1 缓存层设计**（1天）
- [ ] 设计缓存Key生成策略
  ```python
  def generate_cache_key(prompt: str, model: str, temp: float) -> str:
      content = f"{prompt}|{model}|{temp}"
      return hashlib.sha256(content.encode()).hexdigest()
  ```
- [ ] 实现缓存读写装饰器
  ```python
  @cache_llm_response(ttl=3600)
  async def call_llm(prompt: str, model: str):
      # LLM调用
      pass
  ```

**任务4.2 集成到Agent服务**（2天）
- [ ] 为Agent A、B、C添加缓存
- [ ] 实现缓存命中率统计
- [ ] 实现缓存预热（常用提示词）

**任务4.3 缓存管理接口**（1天）
- [ ] GET `/api/cache/stats` - 缓存统计（命中率、大小）
- [ ] DELETE `/api/cache/clear` - 清空缓存
- [ ] POST `/api/cache/invalidate` - 失效特定缓存

**任务4.4 前端缓存指示器**（1天）
- [ ] 显示"来自缓存"标签
- [ ] 缓存管理界面

**验收标准**：
- ✅ 重复请求从缓存返回（<100ms）
- ✅ 缓存命中率>50%
- ✅ 节省API调用成本30%+
- ✅ 提供缓存管理界面

---

### 🌟 P2优先级：高级功能

#### **任务组5：实时协作编辑**（全栈开发E，2周）

**背景**：支持多人同时编辑小说，实时同步修改。

**技术选型**：
- WebSocket - 实时通信
- Yjs - CRDT算法（冲突解决）
- Socket.IO或原生WebSocket

**任务5.1 WebSocket服务**（3天）
- [ ] 实现WebSocket连接管理
- [ ] 实现房间（Room）概念（每个小说一个房间）
- [ ] 实现广播机制

**任务5.2 协作编辑核心**（4天）
- [ ] 集成Yjs库
- [ ] 实现文档同步逻辑
- [ ] 实现光标位置同步
- [ ] 实现在线用户列表

**任务5.3 前端集成**（3天）
- [ ] 集成TipTap + Yjs插件
- [ ] 实现多用户光标展示
- [ ] 实现冲突解决UI

**任务5.4 历史记录**（2天）
- [ ] 记录所有编辑操作
- [ ] 实现时间旅行（回溯历史）

**验收标准**：
- ✅ 多人同时编辑无冲突
- ✅ 实时同步延迟<200ms
- ✅ 支持撤销/重做
- ✅ 显示在线用户列表

---

#### **任务组6：多语言支持（i18n）**（前端开发A/B，1周）

**背景**：支持中英文切换，方便国际用户。

**技术选型**：
- next-i18next - Next.js国际化库

**任务6.1 配置i18n**（1天）
- [ ] 安装next-i18next
- [ ] 配置语言文件结构
  ```
  public/locales/
  ├── zh/
  │   ├── common.json
  │   ├── novel.json
  │   └── generation.json
  └── en/
      ├── common.json
      ├── novel.json
      └── generation.json
  ```

**任务6.2 翻译文案**（2天）
- [ ] 提取所有UI文案
- [ ] 翻译为英文
- [ ] 处理复数和变量

**任务6.3 语言切换器**（1天）
- [ ] 实现语言选择组件
- [ ] 持久化用户选择
- [ ] 动态加载语言包

**验收标准**：
- ✅ 支持中英文切换
- ✅ 所有UI文案已翻译
- ✅ 用户选择持久化

---

### 🎨 P3优先级：可选功能

#### **任务组7：语音转文字输入**（前端开发B，1周）

**背景**：方便用户通过语音输入剧情提示词。

**技术选型**：
- Web Speech API（浏览器原生）
- 或集成第三方服务（讯飞、百度）

**任务7.1 语音识别集成**（2天）
- [ ] 集成Web Speech API
- [ ] 实现录音UI
- [ ] 实现实时转文字

**任务7.2 语音指令**（2天）
- [ ] 支持语音命令（"生成段落"、"保存"）
- [ ] 实现命令解析

**任务7.3 多语言语音识别**（1天）
- [ ] 支持中英文语音识别
- [ ] 自动检测语言

**验收标准**：
- ✅ 语音转文字准确率>85%
- ✅ 支持语音命令
- ✅ 支持中英文

---

## 📊 开发排期总览

```
Week 1: 用户认证 + 章节管理（后端开发C）
Week 2: 导出功能Part1（后端开发D）
Week 3: 导出功能Part2 + 缓存系统（后端开发D）
Week 4: 实时协作Part1（全栈开发E）
Week 5: 实时协作Part2 + 多语言（全栈开发E + 前端）
Week 6: 语音输入 + 测试优化（前端开发B）
```

---

## 🛠️ 依赖和配置

### 新增Python依赖

```txt
# 用户认证
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4

# 导出功能
ebooklib==0.18
WeasyPrint==62.3
celery==5.4.0

# 缓存
redis==5.2.0
```

### 新增前端依赖

```bash
# 协作编辑
npm install yjs y-websocket @tiptap/extension-collaboration

# 多语言
npm install next-i18next

# 语音识别（如需）
npm install react-speech-recognition
```

---

## ✅ 验收检查清单

### 功能完整性
- [ ] 用户可以注册、登录、退出
- [ ] 章节支持完整CRUD操作
- [ ] 小说可导出为EPUB和PDF
- [ ] LLM响应有缓存机制
- [ ] （可选）支持实时协作编辑
- [ ] （可选）支持中英文切换
- [ ] （可选）支持语音输入

### 性能指标
- [ ] 缓存命中率 > 50%
- [ ] API响应时间 < 500ms
- [ ] 导出任务处理时间 < 30s（100章小说）

### 安全性
- [ ] 密码使用bcrypt加密
- [ ] JWT Token有效期设置合理（1天）
- [ ] 敏感接口有权限保护
- [ ] SQL注入防护（使用ORM）

### 代码质量
- [ ] 单元测试覆盖率 > 80%
- [ ] API文档完整（OpenAPI）
- [ ] 代码通过ESLint/Pylint检查

---

## 📞 技术支持和协调

### 每周同步会议
- **时间**：每周五下午3点
- **内容**：
  - 进度汇报
  - 问题讨论
  - 下周计划

### 技术讨论渠道
- **Slack/钉钉**：日常沟通
- **GitHub Issues**：需求和Bug追踪
- **Confluence/Notion**：技术文档

---

**功能扩展，让系统更强大！** 💪
