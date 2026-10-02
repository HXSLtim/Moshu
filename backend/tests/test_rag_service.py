"""RAG持久生命周期、跨实例乱序和检索隔离的确定性测试。"""

import asyncio
import threading
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401  # 注册完整SQLAlchemy模型
from app.db.base import Base
from app.models.novel import Chapter, Novel
from app.models.schemas import RAGQuery
from app.models.user import User
from app.services import rag as rag_service_module
from app.services.rag import RAGService


class FakeCollection:
    """只实现本组测试需要的Chroma collection行为。"""

    def __init__(self):
        self.records = {}
        self._lock = threading.RLock()

    @classmethod
    def _matches(cls, metadata, where):
        if "$and" in where:
            return all(cls._matches(metadata, item) for item in where["$and"])
        for key, expected in where.items():
            actual = metadata.get(key)
            if isinstance(expected, dict):
                if "$lt" in expected and not (actual is not None and actual < expected["$lt"]):
                    return False
                if "$lte" in expected and not (actual is not None and actual <= expected["$lte"]):
                    return False
                if "$gt" in expected and not (actual is not None and actual > expected["$gt"]):
                    return False
                if "$gte" in expected and not (actual is not None and actual >= expected["$gte"]):
                    return False
            elif actual != expected:
                return False
        return True

    def get(self, where, include=None):
        with self._lock:
            ids = [
                record_id
                for record_id, record in self.records.items()
                if self._matches(record["metadata"], where)
            ]
            response = {"ids": ids}
            if include and "metadatas" in include:
                response["metadatas"] = [
                    self.records[record_id]["metadata"] for record_id in ids
                ]
            return response

    def delete(self, ids):
        with self._lock:
            for record_id in ids:
                self.records.pop(record_id, None)


class FakeNode:
    def __init__(self, content, metadata, score=0.9):
        self._content = content
        self.metadata = metadata
        self.score = score

    def get_content(self):
        return self._content


class FakeRetriever:
    def __init__(self, nodes):
        self.nodes = nodes

    def retrieve(self, _query):
        return self.nodes


class FakeIndex:
    def __init__(self, collection, nodes=None):
        self.collection = collection
        self.nodes = nodes or []
        self.retriever_kwargs = None

    def insert(self, document):
        with self.collection._lock:
            self.collection.records[document.id_] = {
                "content": document.get_content(),
                "metadata": dict(document.metadata),
            }

    def as_retriever(self, **kwargs):
        self.retriever_kwargs = kwargs
        return FakeRetriever(self.nodes)


class BlockingOldIndex(FakeIndex):
    """让旧版任务在数据库前置校验后暂停，模拟真实跨进程竞态。"""

    def __init__(self, collection):
        super().__init__(collection)
        self.started = threading.Event()
        self.release = threading.Event()
        self._blocked = False

    def insert(self, document):
        if int(document.metadata["version"]) == 1 and not self._blocked:
            self._blocked = True
            self.started.set()
            assert self.release.wait(timeout=5), "旧索引任务未按预期恢复"
        super().insert(document)


@pytest.mark.asyncio
async def test_disabled_embedding_skips_network_initialization(monkeypatch):
    """显式关闭 Embedding 时不得探测模型或产生重试风暴。"""
    service = RAGService()
    initialize_sync = AsyncMock()
    monkeypatch.setattr(rag_service_module.settings, "EMBEDDING_ENABLED", False)
    monkeypatch.setattr(service, "_initialize_sync", initialize_sync)

    assert await service.initialize() is False
    assert service.initialization_error == "Embedding 服务已通过配置禁用"
    initialize_sync.assert_not_called()


@pytest.fixture
def projection_db(tmp_path, monkeypatch):
    """创建可跨线程访问的文件SQLite，并替换RAG内部会话工厂。"""
    database_path = tmp_path / "rag-projection.sqlite"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )
    testing_session = sessionmaker(
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)

    import app.db.base as db_base

    monkeypatch.setattr(db_base, "SessionLocal", testing_session)
    db = testing_session()
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _create_novel_with_chapter(
    db,
    suffix: str,
    *,
    novel_id=None,
    chapter_id=None,
    content="旧正文",
):
    user = User(
        username=f"rag-owner-{suffix}",
        email=f"rag-owner-{suffix}@example.com",
        hashed_password="not-used",
    )
    db.add(user)
    db.flush()
    novel = Novel(
        id=novel_id,
        title=f"RAG小说{suffix}",
        worldview=f"世界观{suffix}",
        user_id=user.id,
    )
    db.add(novel)
    db.flush()
    chapter = Chapter(
        id=chapter_id,
        novel_id=novel.id,
        chapter_number=1,
        title="第一章",
        content=content,
        word_count=len(content),
    )
    db.add(chapter)
    db.commit()
    return user, novel, chapter


def _ready_service(collection, index=None):
    service = RAGService()
    service.collection = collection
    service.index = index or FakeIndex(collection)
    service.available = True
    service.initialize = AsyncMock(return_value=True)

    def cleanup_without_chroma(where_filters):
        ids = set()
        for where in where_filters:
            ids.update(collection.get(where=where).get("ids") or [])
        collection.delete(ids=list(ids))
        return len(ids)

    service._cleanup_across_collections_sync = cleanup_without_chroma
    return service


def _metadata(service, db, novel, chapter):
    return {
        "source": "chapter",
        "chapter_id": chapter.id,
        "version": chapter.version,
        **service.prepare_chapter_projection(novel.id, chapter.id, db=db),
    }


def test_service_construction_is_lazy():
    """构造服务不会连接模型、访问磁盘或导入Chroma。"""
    service = RAGService()
    assert service.available is False
    assert service._initialized is False
    assert service.index is None


@pytest.mark.asyncio
async def test_two_instances_cannot_commit_old_version_after_new_projection(
    projection_db,
):
    """两个服务实例乱序写入时，旧任务在后置栅栏处撤销自己的分块。"""
    db = projection_db
    _, novel, chapter = _create_novel_with_chapter(db, "race")
    collection = FakeCollection()
    blocking_index = BlockingOldIndex(collection)
    old_service = _ready_service(collection, blocking_index)
    new_service = _ready_service(collection)
    old_metadata = _metadata(old_service, db, novel, chapter)

    old_task = asyncio.create_task(
        old_service.index_content(
            novel.id,
            chapter.chapter_number,
            chapter.content,
            old_metadata,
        )
    )
    assert await asyncio.to_thread(blocking_index.started.wait, 2)

    db.execute(
        update(Chapter)
        .where(Chapter.id == chapter.id)
        .values(content="新正文", word_count=3, version=Chapter.version + 1)
    )
    db.commit()
    db.expire(chapter)
    new_metadata = _metadata(new_service, db, novel, chapter)
    assert await new_service.index_content(
        novel.id,
        chapter.chapter_number,
        chapter.content,
        new_metadata,
    ) is True

    blocking_index.release.set()
    assert await old_task is True

    assert len(collection.records) == 1
    only_record = next(iter(collection.records.values()))
    assert only_record["content"] == "新正文"
    assert only_record["metadata"]["version"] == 2
    assert only_record["metadata"]["_source_lifecycle"] == chapter.rag_lifecycle_id


@pytest.mark.asyncio
async def test_deleted_novel_primary_key_reuse_cannot_cross_tenant_recall(
    projection_db,
):
    """删书后整数主键复用时，旧写入、旧清理和旧向量都不能影响新作者。"""
    db = projection_db
    old_user, old_novel, old_chapter = _create_novel_with_chapter(
        db,
        "old",
        novel_id=77,
        chapter_id=88,
        content="旧作者正文",
    )
    collection = FakeCollection()
    old_service = _ready_service(collection)
    new_service = _ready_service(collection)
    old_metadata = _metadata(old_service, db, old_novel, old_chapter)
    assert await old_service.index_content(77, 1, "旧作者正文", old_metadata) is True
    old_record = next(iter(collection.records.values())).copy()
    old_record["metadata"] = dict(old_record["metadata"])
    deletion_token = old_service.mark_novel_deleted(77, db=db)
    old_lifecycle = old_novel.rag_lifecycle_id

    db.delete(old_novel)
    db.commit()
    db.expunge_all()
    new_user, new_novel, new_chapter = _create_novel_with_chapter(
        db,
        "new",
        novel_id=77,
        chapter_id=88,
        content="新作者正文",
    )
    assert new_user.id != old_user.id
    assert new_novel.rag_lifecycle_id != old_lifecycle

    new_metadata = _metadata(new_service, db, new_novel, new_chapter)
    assert await new_service.index_content(77, 1, "新作者正文", new_metadata) is True

    # 删除前排队的旧任务在新作品出现后到达，也不能重新写入旧作者内容。
    assert await old_service.index_content(77, 1, "旧作者正文", old_metadata) is True
    assert await old_service.cleanup_novel_vectors(
        77,
        deletion_token=deletion_token,
    ) == 1
    assert len(collection.records) == 1
    assert next(iter(collection.records.values()))["content"] == "新作者正文"

    # FakeRetriever故意忽略下推过滤，验证数据库后置过滤仍拒绝旧生命周期。
    current_record = next(iter(collection.records.values()))
    new_service.index = FakeIndex(
        collection,
        nodes=[
            FakeNode("旧作者正文", old_record["metadata"], score=0.99),
            FakeNode("新作者正文", current_record["metadata"], score=0.90),
        ],
    )
    response = await new_service.hybrid_search(
        RAGQuery(novel_id=77, query="正文", top_k=3)
    )
    assert [item.content for item in response.results] == ["新作者正文"]
    filters = new_service.index.retriever_kwargs["filters"].filters
    assert [(item.key, item.value) for item in filters] == [
        ("novel_id", 77),
        ("_owner_id", new_user.id),
        ("_novel_lifecycle", new_novel.rag_lifecycle_id),
    ]


@pytest.mark.asyncio
async def test_reindex_removes_stale_tail_chunks(projection_db):
    """正文缩短后，同一数据库版本只保留当前内容的分块。"""
    db = projection_db
    _, novel, chapter = _create_novel_with_chapter(db, "tail", content="旧" * 1200)
    collection = FakeCollection()
    service = _ready_service(collection)
    assert await service.index_content(
        novel.id,
        1,
        chapter.content,
        _metadata(service, db, novel, chapter),
    ) is True
    assert len(collection.records) == 3

    db.execute(
        update(Chapter)
        .where(Chapter.id == chapter.id)
        .values(content="新正文", word_count=3, version=Chapter.version + 1)
    )
    db.commit()
    db.expire(chapter)
    assert await service.index_content(
        novel.id,
        1,
        chapter.content,
        _metadata(service, db, novel, chapter),
    ) is True
    assert len(collection.records) == 1
    assert next(iter(collection.records.values()))["content"] == "新正文"


@pytest.mark.asyncio
async def test_search_pushes_owner_lifecycle_and_chapter_filters(projection_db):
    """租户、作品生命周期和最大章节限制都在召回前下推。"""
    db = projection_db
    user, novel, chapter = _create_novel_with_chapter(db, "search", content="目标内容")
    collection = FakeCollection()
    service = _ready_service(collection)
    assert await service.index_content(
        novel.id,
        1,
        chapter.content,
        _metadata(service, db, novel, chapter),
    ) is True
    record = next(iter(collection.records.values()))
    service.index = FakeIndex(
        collection,
        nodes=[FakeNode(record["content"], record["metadata"])],
    )

    response = await service.hybrid_search(
        RAGQuery(novel_id=novel.id, query="角色设定", max_chapter=5, top_k=3)
    )

    assert [item.content for item in response.results] == ["目标内容"]
    assert "novel_id" not in response.results[0].metadata
    assert all(not key.startswith("_") for key in response.results[0].metadata)
    assert service.index.retriever_kwargs["similarity_top_k"] == 12
    filters = service.index.retriever_kwargs["filters"].filters
    assert [(item.key, item.value, item.operator.value) for item in filters] == [
        ("novel_id", novel.id, "=="),
        ("_owner_id", user.id, "=="),
        ("_novel_lifecycle", novel.rag_lifecycle_id, "=="),
        ("chapter", 5, "<="),
    ]


def test_split_text_respects_limit_and_ignores_blank_chunks():
    service = RAGService()
    chunks = service._split_text("A" * 1000 + " " * 500, chunk_size=500)
    assert chunks == ["A" * 500, "A" * 500]
