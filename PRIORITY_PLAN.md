# 优先级推进计划（应急方案）

> 状态：历史草案，已归档。本文中的默认密钥、接口清单和实施步骤不代表当前系统，禁止直接复制到运行环境；当前事实以 `README.md`、`ARCHITECTURE.md`、实际代码和自动化测试为准。

**制定日期**：2025-11-14
**背景**：前端人员招聘中，后端可先行推进
**目标**：在前端人员到位前，完成所有后端API，确保前端开发无阻塞

---

## 🎯 核心策略

**在前端人员到位前，优先完成**：
1. ✅ 用户认证系统（后端完整实现）
2. ✅ 小说管理API（CRUD）
3. ✅ 角色管理API（CRUD）
4. ✅ 章节管理API（CRUD）
5. ✅ 世界观管理API（CRUD）

**优势**：
- 前端开发无需等待后端
- 前端可以立即开始联调
- 降低项目风险

---

## 📅 优先级任务清单（P0 - 最高优先级）

### Phase 1：用户认证系统（3天）

**优先级**：⭐⭐⭐⭐⭐（最高）
**负责人**：BE-A（暂代BE-C）
**依赖**：无

#### Day 1：数据模型和工具函数

**任务1.1：创建User数据模型**

文件：`backend/app/models/user.py`

```python
"""
用户数据模型
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from app.db.base import Base


class User(Base):
    """用户模型"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<User {self.username}>"
```

**任务1.2：创建安全工具函数**

文件：`backend/app/core/security.py`

```python
"""
安全相关工具函数（JWT、密码哈希）
"""
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from app.core.config import settings

# 密码加密上下文
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT配置
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7天


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """生成密码哈希"""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    创建JWT访问令牌

    Args:
        data: 要编码的数据（通常包含用户ID）
        expires_delta: 过期时间增量

    Returns:
        JWT令牌字符串
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> Optional[dict]:
    """
    验证JWT令牌

    Args:
        token: JWT令牌字符串

    Returns:
        解码后的数据，如果验证失败返回None
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None
```

**任务1.3：安装依赖**

```bash
cd backend
pip install python-jose[cryptography] passlib[bcrypt] python-multipart
```

**任务1.4：更新配置**

编辑 `backend/app/core/config.py`，确保有 `SECRET_KEY`：

```python
class Settings(BaseSettings):
    # ...
    SECRET_KEY: str = "change_this_in_production"  # 已存在
```

---

#### Day 2：认证API

**任务2.1：创建Pydantic Schemas**

文件：`backend/app/models/schemas.py`（添加以下内容）

```python
# 用户相关Schema
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime


class UserBase(BaseModel):
    """用户基础Schema"""
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr


class UserCreate(UserBase):
    """用户创建Schema"""
    password: str = Field(..., min_length=6, max_length=50)


class UserLogin(BaseModel):
    """用户登录Schema"""
    username: str
    password: str


class UserResponse(UserBase):
    """用户响应Schema"""
    id: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    """Token响应Schema"""
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
```

**任务2.2：创建数据库操作**

文件：`backend/app/crud/user.py`

```python
"""
用户CRUD操作
"""
from typing import Optional
from sqlalchemy.orm import Session
from app.models.user import User
from app.models.schemas import UserCreate
from app.core.security import get_password_hash, verify_password


def get_user_by_username(db: Session, username: str) -> Optional[User]:
    """根据用户名获取用户"""
    return db.query(User).filter(User.username == username).first()


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    """根据邮箱获取用户"""
    return db.query(User).filter(User.email == email).first()


def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    """根据ID获取用户"""
    return db.query(User).filter(User.id == user_id).first()


def create_user(db: Session, user: UserCreate) -> User:
    """创建用户"""
    hashed_password = get_password_hash(user.password)
    db_user = User(
        username=user.username,
        email=user.email,
        hashed_password=hashed_password
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    """验证用户"""
    user = get_user_by_username(db, username)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user
```

**任务2.3：创建数据库会话依赖**

文件：`backend/app/db/base.py`

```python
"""
数据库基础配置
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

# 使用SQLite（简化）
SQLALCHEMY_DATABASE_URL = "sqlite:///./novel.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False}  # SQLite需要
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

**任务2.4：创建依赖注入函数**

文件：`backend/app/api/dependencies.py`

```python
"""
API依赖注入
"""
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.core.security import verify_token
from app.crud.user import get_user_by_id
from app.models.user import User

# HTTP Bearer认证
security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """
    获取当前登录用户

    从JWT Token中解析用户信息
    """
    token = credentials.credentials
    payload = verify_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证令牌"
        )

    user_id: Optional[int] = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证令牌"
        )

    user = get_user_by_id(db, user_id=int(user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在"
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户已被禁用"
        )

    return user


async def get_current_active_superuser(
    current_user: User = Depends(get_current_user)
) -> User:
    """获取当前超级管理员"""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="权限不足"
        )
    return current_user
```

**任务2.5：创建认证路由**

文件：`backend/app/api/routes/auth.py`

```python
"""
用户认证路由
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.models.schemas import UserCreate, UserLogin, UserResponse, Token
from app.crud.user import (
    get_user_by_username,
    get_user_by_email,
    create_user,
    authenticate_user
)
from app.core.security import create_access_token
from app.api.dependencies import get_current_user
from app.models.user import User
from loguru import logger

router = APIRouter()


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(user: UserCreate, db: Session = Depends(get_db)):
    """
    用户注册

    创建新用户账号
    """
    # 检查用户名是否已存在
    if get_user_by_username(db, username=user.username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已存在"
        )

    # 检查邮箱是否已存在
    if get_user_by_email(db, email=user.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邮箱已被注册"
        )

    # 创建用户
    db_user = create_user(db, user)

    # 生成Token
    access_token = create_access_token(data={"sub": str(db_user.id)})

    logger.info(f"新用户注册：{db_user.username}")

    return Token(
        access_token=access_token,
        user=UserResponse.from_orm(db_user)
    )


@router.post("/login", response_model=Token)
async def login(credentials: UserLogin, db: Session = Depends(get_db)):
    """
    用户登录

    使用用户名和密码登录，返回JWT Token
    """
    user = authenticate_user(db, credentials.username, credentials.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户已被禁用"
        )

    # 生成Token
    access_token = create_access_token(data={"sub": str(user.id)})

    logger.info(f"用户登录：{user.username}")

    return Token(
        access_token=access_token,
        user=UserResponse.from_orm(user)
    )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """
    获取当前用户信息

    需要认证
    """
    return UserResponse.from_orm(current_user)
```

**任务2.6：注册路由到主应用**

编辑 `backend/app/main.py`：

```python
from app.api.routes import generation, health, auth  # 添加auth

# 注册路由
app.include_router(health.router, prefix="/api", tags=["健康检查"])
app.include_router(auth.router, prefix="/api/auth", tags=["用户认证"])  # 新增
app.include_router(generation.router, prefix="/api/generation", tags=["内容生成"])
```

---

#### Day 3：数据库初始化和测试

**任务3.1：创建数据库初始化脚本**

文件：`backend/init_db.py`

```python
"""
初始化数据库
"""
from app.db.base import Base, engine
from app.models.user import User  # 导入所有模型

print("创建数据库表...")
Base.metadata.create_all(bind=engine)
print("数据库初始化完成！")
```

运行：
```bash
cd backend
python init_db.py
```

**任务3.2：测试认证API**

```bash
# 测试注册
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "username": "testuser",
    "email": "test@example.com",
    "password": "password123"
  }'

# 测试登录
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "testuser",
    "password": "password123"
  }'

# 测试获取当前用户（需要替换YOUR_TOKEN）
curl http://localhost:8000/api/auth/me \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**任务3.3：保护现有API**

编辑 `backend/app/api/routes/generation.py`：

```python
from app.api.dependencies import get_current_user
from app.models.user import User

@router.post("/generate", response_model=GenerationResponse)
async def generate_content(
    request: GenerationRequest,
    current_user: User = Depends(get_current_user)  # 添加认证
):
    """生成小说内容（需要认证）"""
    # ...

@router.get("/test")
async def test_generation(
    current_user: User = Depends(get_current_user)  # 添加认证
):
    """测试接口（需要认证）"""
    # ...
```

---

### Phase 2：小说管理API（2天）

**优先级**：⭐⭐⭐⭐⭐
**前置依赖**：用户认证系统

#### Day 4-5：Novel CRUD API

**任务4.1：创建Novel数据模型**

文件：`backend/app/models/novel.py`

```python
"""
小说数据模型
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base


class Novel(Base):
    """小说模型"""
    __tablename__ = "novels"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    genre = Column(String(50), nullable=True)  # 题材类型
    status = Column(String(20), default="draft")  # draft, writing, completed
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # 关系
    author = relationship("User", backref="novels")
    chapters = relationship("Chapter", back_populates="novel", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Novel {self.title}>"
```

**任务4.2：创建Novel Schemas**

添加到 `backend/app/models/schemas.py`：

```python
class NovelBase(BaseModel):
    """小说基础Schema"""
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    genre: Optional[str] = None
    status: str = "draft"


class NovelCreate(NovelBase):
    """小说创建Schema"""
    pass


class NovelUpdate(BaseModel):
    """小说更新Schema"""
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    genre: Optional[str] = None
    status: Optional[str] = None


class NovelResponse(NovelBase):
    """小说响应Schema"""
    id: int
    author_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
```

**任务4.3：创建Novel CRUD**

文件：`backend/app/crud/novel.py`

```python
"""
小说CRUD操作
"""
from typing import List, Optional
from sqlalchemy.orm import Session
from app.models.novel import Novel
from app.models.schemas import NovelCreate, NovelUpdate


def get_novel(db: Session, novel_id: int) -> Optional[Novel]:
    """获取单个小说"""
    return db.query(Novel).filter(Novel.id == novel_id).first()


def get_novels(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    author_id: Optional[int] = None
) -> List[Novel]:
    """获取小说列表"""
    query = db.query(Novel)
    if author_id:
        query = query.filter(Novel.author_id == author_id)
    return query.offset(skip).limit(limit).all()


def create_novel(db: Session, novel: NovelCreate, author_id: int) -> Novel:
    """创建小说"""
    db_novel = Novel(**novel.dict(), author_id=author_id)
    db.add(db_novel)
    db.commit()
    db.refresh(db_novel)
    return db_novel


def update_novel(
    db: Session,
    novel_id: int,
    novel_update: NovelUpdate
) -> Optional[Novel]:
    """更新小说"""
    db_novel = get_novel(db, novel_id)
    if not db_novel:
        return None

    update_data = novel_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_novel, field, value)

    db.commit()
    db.refresh(db_novel)
    return db_novel


def delete_novel(db: Session, novel_id: int) -> bool:
    """删除小说"""
    db_novel = get_novel(db, novel_id)
    if not db_novel:
        return False

    db.delete(db_novel)
    db.commit()
    return True
```

**任务4.4：创建Novel路由**

文件：`backend/app/api/routes/novels.py`

```python
"""
小说管理路由
"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.models.schemas import NovelCreate, NovelUpdate, NovelResponse
from app.crud import novel as novel_crud
from app.api.dependencies import get_current_user
from app.models.user import User
from loguru import logger

router = APIRouter()


@router.get("/", response_model=List[NovelResponse])
async def get_novels(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取小说列表

    返回当前用户的所有小说
    """
    novels = novel_crud.get_novels(
        db,
        skip=skip,
        limit=limit,
        author_id=current_user.id
    )
    return [NovelResponse.from_orm(novel) for novel in novels]


@router.post("/", response_model=NovelResponse, status_code=status.HTTP_201_CREATED)
async def create_novel(
    novel: NovelCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    创建小说
    """
    db_novel = novel_crud.create_novel(db, novel, author_id=current_user.id)
    logger.info(f"用户 {current_user.username} 创建小说：{db_novel.title}")
    return NovelResponse.from_orm(db_novel)


@router.get("/{novel_id}", response_model=NovelResponse)
async def get_novel(
    novel_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取小说详情
    """
    db_novel = novel_crud.get_novel(db, novel_id)
    if not db_novel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="小说不存在"
        )

    # 验证权限
    if db_novel.author_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权访问此小说"
        )

    return NovelResponse.from_orm(db_novel)


@router.put("/{novel_id}", response_model=NovelResponse)
async def update_novel(
    novel_id: int,
    novel_update: NovelUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    更新小说
    """
    db_novel = novel_crud.get_novel(db, novel_id)
    if not db_novel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="小说不存在"
        )

    # 验证权限
    if db_novel.author_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权修改此小说"
        )

    updated_novel = novel_crud.update_novel(db, novel_id, novel_update)
    logger.info(f"用户 {current_user.username} 更新小说：{updated_novel.title}")
    return NovelResponse.from_orm(updated_novel)


@router.delete("/{novel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_novel(
    novel_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    删除小说
    """
    db_novel = novel_crud.get_novel(db, novel_id)
    if not db_novel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="小说不存在"
        )

    # 验证权限
    if db_novel.author_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权删除此小说"
        )

    novel_crud.delete_novel(db, novel_id)
    logger.info(f"用户 {current_user.username} 删除小说：{db_novel.title}")
    return None
```

**任务4.5：注册路由**

编辑 `backend/app/main.py`：

```python
from app.api.routes import generation, health, auth, novels  # 添加novels

app.include_router(novels.router, prefix="/api/novels", tags=["小说管理"])  # 新增
```

---

### Phase 3：章节管理API（2天）

**优先级**：⭐⭐⭐⭐
**详细实现**：参考上面Novel的模式，创建Chapter模型、CRUD、路由

---

### Phase 4：角色/世界观管理API（3天）

**优先级**：⭐⭐⭐
**按需实现**：Character、Worldview模型

---

## 📊 实施时间表（前端到位前）

| 时间 | 任务 | 交付物 | 状态 |
|------|------|--------|------|
| **Day 1** | 数据模型+安全工具 | User模型、JWT工具 | 🔴 待开始 |
| **Day 2** | 认证API | 注册/登录接口 | 🔴 待开始 |
| **Day 3** | 数据库初始化+测试 | 可用的认证系统 | 🔴 待开始 |
| **Day 4-5** | 小说管理API | Novel CRUD | 🔴 待开始 |
| **Day 6-7** | 章节管理API | Chapter CRUD | 🔴 待开始 |
| **Day 8-10** | 角色/世界观API | Character/Worldview CRUD | 🔴 待开始 |

**预期成果**：10天后，所有后端API就绪，前端开发无阻塞

---

## ✅ 立即开始（现在就做）

### Step 1：创建目录结构

```bash
cd C:\Users\a2778\Desktop\code\Nai\backend

# 创建必要的目录
mkdir -p app/models app/crud app/db
```

### Step 2：开始实现用户认证

**我现在就可以帮您实现**：
1. 创建User模型
2. 创建JWT工具函数
3. 创建认证API
4. 测试认证流程

**是否开始？** 我会按照上面的详细步骤逐步实现。

---

## 🎯 成功标准

**认证系统完成标准**：
- [ ] 用户可以注册（POST /api/auth/register）
- [ ] 用户可以登录（POST /api/auth/login）
- [ ] 返回有效JWT Token
- [ ] Token可以验证（GET /api/auth/me）
- [ ] 现有API需要认证才能访问

**小说管理完成标准**：
- [ ] 创建小说（POST /api/novels）
- [ ] 获取小说列表（GET /api/novels）
- [ ] 获取小说详情（GET /api/novels/{id}）
- [ ] 更新小说（PUT /api/novels/{id}）
- [ ] 删除小说（DELETE /api/novels/{id}）
- [ ] 权限验证（仅作者可编辑）

---

**准备好了吗？我们从Day 1的任务1.1开始：创建User数据模型！** 🚀
