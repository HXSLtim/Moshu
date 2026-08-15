"""
小说CRUD操作
"""
from typing import List, Optional

from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.text_stats import count_text_units
from app.models.novel import Novel, Chapter, StyleSample
from app.models.schemas import (
    ChapterCreate,
    ChapterNextCreate,
    ChapterUpdate,
    NovelCreate,
    NovelUpdate,
    StyleSampleCreate,
)


class ChapterNumberConflictError(Exception):
    """同一小说中的章节号发生冲突。"""


class ChapterVersionConflictError(Exception):
    """客户端基于旧版本更新章节。"""

    def __init__(self, current_version: int):
        self.current_version = current_version
        super().__init__(f"章节已更新，当前版本为 {current_version}")


# ========== Novel CRUD ==========

def get_novel_by_id(db: Session, novel_id: int) -> Optional[Novel]:
    """根据ID获取小说"""
    return db.query(Novel).filter(Novel.id == novel_id).first()


def get_novels_by_user(
    db: Session,
    user_id: int,
    skip: int = 0,
    limit: int = 100
) -> List[Novel]:
    """
    获取用户的所有小说

    Args:
        db: 数据库会话
        user_id: 用户ID
        skip: 跳过条数
        limit: 返回条数限制

    Returns:
        小说列表
    """
    return db.query(Novel).filter(
        Novel.user_id == user_id
    ).offset(skip).limit(limit).all()


def get_novel_statistics_by_user(db: Session, user_id: int) -> List[dict]:
    """用单条聚合查询返回当前用户每部小说的章节数和总字数。"""
    rows = (
        db.query(
            Novel.id.label("novel_id"),
            func.count(Chapter.id).label("chapter_count"),
            func.coalesce(func.sum(Chapter.word_count), 0).label("total_words"),
        )
        .outerjoin(Chapter, Chapter.novel_id == Novel.id)
        .filter(Novel.user_id == user_id)
        .group_by(Novel.id)
        .order_by(Novel.id)
        .all()
    )
    return [
        {
            "novel_id": int(row.novel_id),
            "chapter_count": int(row.chapter_count),
            "total_words": int(row.total_words),
        }
        for row in rows
    ]


def create_novel(db: Session, novel: NovelCreate, user_id: int) -> Novel:
    """
    创建小说

    Args:
        db: 数据库会话
        novel: 小说创建Schema
        user_id: 作者用户ID

    Returns:
        创建的小说对象
    """
    db_novel = Novel(
        title=novel.title,
        genre=novel.genre,
        description=novel.description,
        worldview=novel.worldview,
        user_id=user_id
    )
    db.add(db_novel)
    db.commit()
    db.refresh(db_novel)
    return db_novel


def update_novel(
    db: Session,
    novel_id: int,
    novel_update: NovelUpdate
) -> Optional[Novel]:
    """
    更新小说

    Args:
        db: 数据库会话
        novel_id: 小说ID
        novel_update: 小说更新Schema

    Returns:
        更新后的小说对象，如果不存在返回None
    """
    if get_novel_by_id(db, novel_id) is None:
        return None

    # 世界观版本必须由数据库原子递增，不能依赖进程内对象的读改写。
    update_data = novel_update.model_dump(exclude_unset=True)
    if "worldview" in update_data:
        update_data["rag_revision"] = Novel.rag_revision + 1

    db.execute(
        update(Novel)
        .where(Novel.id == novel_id)
        .values(**update_data)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return get_novel_by_id(db, novel_id)


def delete_novel(db: Session, novel_id: int) -> bool:
    """
    删除小说（级联删除所有章节）

    Args:
        db: 数据库会话
        novel_id: 小说ID

    Returns:
        删除成功返回True，小说不存在返回False
    """
    db_novel = get_novel_by_id(db, novel_id)
    if not db_novel:
        return False

    db.delete(db_novel)
    db.commit()
    return True


# ========== Chapter CRUD ==========

def get_chapter_by_id(db: Session, chapter_id: int) -> Optional[Chapter]:
    """根据ID获取章节"""
    return db.query(Chapter).filter(Chapter.id == chapter_id).first()


def get_chapter_by_number(
    db: Session,
    novel_id: int,
    chapter_number: int
) -> Optional[Chapter]:
    """根据章节号获取章节"""
    return db.query(Chapter).filter(
        Chapter.novel_id == novel_id,
        Chapter.chapter_number == chapter_number
    ).first()


def get_chapters_by_novel(
    db: Session,
    novel_id: int,
    skip: int = 0,
    limit: Optional[int] = None,
) -> List[Chapter]:
    """
    获取小说的所有章节

    Args:
        db: 数据库会话
        novel_id: 小说ID
        skip: 跳过条数
        limit: 返回条数限制

    Returns:
        章节列表（按章节号排序）
    """
    query = db.query(Chapter).filter(
        Chapter.novel_id == novel_id
    ).order_by(Chapter.chapter_number).offset(skip)
    if limit is not None:
        query = query.limit(limit)
    return query.all()


def count_chapters_by_novel(db: Session, novel_id: int) -> int:
    """统计小说章节总数。"""
    return db.query(func.count(Chapter.id)).filter(Chapter.novel_id == novel_id).scalar() or 0


def get_max_chapter_number(db: Session, novel_id: int) -> int:
    """获取小说当前最大的章节号；没有章节时返回0。"""
    return db.query(func.max(Chapter.chapter_number)).filter(
        Chapter.novel_id == novel_id
    ).scalar() or 0


def get_latest_chapter(db: Session, novel_id: int) -> Optional[Chapter]:
    """只读取小说最后一章，避免为获取参考章节加载全部正文。"""
    return (
        db.query(Chapter)
        .filter(Chapter.novel_id == novel_id)
        .order_by(Chapter.chapter_number.desc())
        .first()
    )


def create_chapter(
    db: Session,
    novel_id: int,
    chapter: ChapterCreate
) -> Chapter:
    """
    创建章节

    Args:
        db: 数据库会话
        novel_id: 小说ID
        chapter: 章节创建Schema

    Returns:
        创建的章节对象
    """
    # 计算字数
    word_count = count_text_units(chapter.content)

    db_chapter = Chapter(
        novel_id=novel_id,
        chapter_number=chapter.chapter_number,
        title=chapter.title,
        content=chapter.content,
        word_count=word_count
    )
    db.add(db_chapter)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ChapterNumberConflictError(
            f"章节 {chapter.chapter_number} 已存在"
        ) from exc
    db.refresh(db_chapter)
    return db_chapter


def create_next_chapter(
    db: Session,
    novel_id: int,
    chapter: ChapterNextCreate,
    max_attempts: int = 3,
) -> Chapter:
    """由服务端分配下一章节号，并在并发冲突时进行有限重试。"""
    for _ in range(max_attempts):
        chapter_number = get_max_chapter_number(db, novel_id) + 1
        db_chapter = Chapter(
            novel_id=novel_id,
            chapter_number=chapter_number,
            title=chapter.title or f"第{chapter_number}章",
            content=chapter.content,
            word_count=count_text_units(chapter.content),
        )
        db.add(db_chapter)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            continue
        db.refresh(db_chapter)
        return db_chapter

    raise ChapterNumberConflictError("分配下一章节号时发生并发冲突，请重试")


def update_chapter(
    db: Session,
    chapter_id: int,
    chapter_update: ChapterUpdate
) -> Optional[Chapter]:
    """
    更新章节

    Args:
        db: 数据库会话
        chapter_id: 章节ID
        chapter_update: 章节更新Schema

    Returns:
        更新后的章节对象，如果不存在返回None
    """
    update_data = chapter_update.model_dump(
        exclude_unset=True,
        exclude_none=True,
        exclude={"expected_version"},
    )
    if "content" in update_data:
        update_data["word_count"] = count_text_units(update_data["content"])

    statement = (
        update(Chapter)
        .where(
            Chapter.id == chapter_id,
            Chapter.version == chapter_update.expected_version,
        )
        .values(**update_data, version=Chapter.version + 1)
        .execution_options(synchronize_session=False)
    )

    try:
        result = db.execute(statement)
        if result.rowcount != 1:
            db.rollback()
            current = get_chapter_by_id(db, chapter_id)
            if current is None:
                return None
            raise ChapterVersionConflictError(current.version)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ChapterNumberConflictError("目标章节号已存在") from exc

    return get_chapter_by_id(db, chapter_id)


def delete_chapter(db: Session, chapter_id: int) -> bool:
    """
    删除章节。RAG等派生数据由路由安排后台幂等清理。

    Args:
        db: 数据库会话
        chapter_id: 章节ID

    Returns:
        删除成功返回True，章节不存在返回False
    """
    db_chapter = get_chapter_by_id(db, chapter_id)
    if not db_chapter:
        return False

    try:
        db.delete(db_chapter)
        db.commit()
        return True
    except Exception:
        db.rollback()
        return False


# ========== StyleSample CRUD ==========

def get_style_sample_by_id(db: Session, sample_id: int) -> Optional[StyleSample]:
    """根据ID获取文风样本"""
    return db.query(StyleSample).filter(StyleSample.id == sample_id).first()


def get_style_samples_by_novel(
    db: Session,
    novel_id: int
) -> List[StyleSample]:
    """获取小说下的所有文风样本"""
    return db.query(StyleSample).filter(StyleSample.novel_id == novel_id).order_by(StyleSample.id.desc()).all()


def create_style_sample(
    db: Session,
    style_sample: StyleSampleCreate
) -> StyleSample:
    """创建文风样本"""
    db_sample = StyleSample(
        novel_id=style_sample.novel_id,
        name=style_sample.name,
        sample_text=style_sample.sample_text,
        style_features=None,
    )
    db.add(db_sample)
    db.commit()
    db.refresh(db_sample)
    return db_sample
