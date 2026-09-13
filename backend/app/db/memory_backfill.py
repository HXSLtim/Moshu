"""当前原文版本的幂等回填；不推测历史，不自动触发付费提取。"""
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

import sqlalchemy as sa


class MemoryBackfillError(RuntimeError):
    """旧数据的归属或版本不完整，需要作者核对后再迁移。"""


def current_chapter_snapshots(connection) -> list[dict]:
    """在新增表之前预检原文归属，拒绝让 SQLite 留下半套迁移。"""
    metadata = sa.MetaData()
    chapters = sa.Table("chapters", metadata, autoload_with=connection)
    novels = sa.Table("novels", metadata, autoload_with=connection)
    source = chapters.outerjoin(novels, chapters.c.novel_id == novels.c.id)
    rows = connection.execute(sa.select(
        chapters.c.id.label("chapter_id"), chapters.c.novel_id,
        novels.c.rag_lifecycle_id.label("novel_lifecycle_id"),
        chapters.c.rag_lifecycle_id.label("chapter_lifecycle_id"),
        chapters.c.version, chapters.c.chapter_number, chapters.c.title, chapters.c.content,
    ).select_from(source)).mappings()
    snapshots = []
    for row in rows:
        if (not row["novel_lifecycle_id"] or not row["chapter_lifecycle_id"]
                or not isinstance(row["version"], int) or row["version"] < 1
                or not isinstance(row["content"], str) or not isinstance(row["title"], str)):
            raise MemoryBackfillError(
                f"无法回填 chapter_id={row['chapter_id']}, novel_id={row['novel_id']}："
                "父作品、生命周期、版本或原文缺失；请备份后核对，不会删除或猜测原文。"
            )
        snapshots.append({**row, "content_hash": sha256(row["content"].encode("utf-8")).hexdigest()})
    return snapshots


def backfill_current_chapter_revisions(connection) -> int:
    """在调用方事务内只补当前版本，已存在但不一致的快照拒绝覆盖。"""
    snapshots = current_chapter_snapshots(connection)
    revisions = sa.Table("chapter_revisions", sa.MetaData(), autoload_with=connection)
    pending = []
    for snapshot in snapshots:
        existing = connection.execute(sa.select(revisions).where(
            revisions.c.chapter_lifecycle_id == snapshot["chapter_lifecycle_id"],
            revisions.c.version == snapshot["version"],
        )).mappings().first()
        if existing:
            if any(existing[key] != value for key, value in snapshot.items()):
                raise MemoryBackfillError(f"chapter_id={snapshot['chapter_id']} 当前版本与历史快照不一致，禁止覆盖。")
            continue
        pending.append({**snapshot, "id": str(uuid4()), "created_at": datetime.now(timezone.utc).replace(tzinfo=None)})
    if pending:
        connection.execute(revisions.insert(), pending)
    return len(pending)
