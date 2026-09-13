"""基于 Chroma 与 OpenAI-compatible Embedding 的小说检索服务。"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from loguru import logger

from app.core.config import settings
from app.models.schemas import RAGQuery, RAGResponse, RAGResult


@dataclass(frozen=True)
class NovelProjectionTruth:
    """数据库中的当前小说投影身份。"""

    novel_id: int
    owner_id: int
    lifecycle_id: str
    rag_revision: int
    worldview_hash: str


@dataclass(frozen=True)
class SourceProjectionTruth:
    """一次索引写入必须匹配的数据库真源。"""

    novel_id: int
    owner_id: int
    novel_lifecycle_id: str
    source: str
    source_lifecycle_id: str
    source_key: str
    version: int
    content_hash: str
    chapter_id: Optional[int] = None
    chapter_number: int = 0


class RAGService:
    """管理可重建的小说向量投影。

    初始化过程可能访问本地模型服务，因此模块导入时不做任何网络或模型加载。
    """

    def __init__(self, retry_interval_seconds: float = 30.0):
        self.available = False
        self.vector_store = None
        self.embed_model = None
        self.index = None
        self.collection = None
        self.embed_dim: Optional[int] = None
        self.collection_name: Optional[str] = None
        self.initialization_error: Optional[str] = None

        self._initialized = False
        self._init_lock = asyncio.Lock()
        self._novel_locks: Dict[int, asyncio.Lock] = {}
        self._source_locks: Dict[str, asyncio.Lock] = {}
        self._last_init_attempt = 0.0
        self._retry_interval_seconds = retry_interval_seconds

    async def initialize(self, force: bool = False) -> bool:
        """按需初始化 embedding、Chroma 和持久索引。"""
        if not settings.EMBEDDING_ENABLED:
            first_disabled_check = not self._initialized
            self.available = False
            self._initialized = True
            self._last_init_attempt = time.monotonic()
            self.initialization_error = "Embedding 服务已通过配置禁用"
            if first_disabled_check:
                logger.info(self.initialization_error)
            return False

        if self.available and not force:
            return True

        now = time.monotonic()
        if (
            self._initialized
            and not force
            and now - self._last_init_attempt < self._retry_interval_seconds
        ):
            return False

        async with self._init_lock:
            if self.available and not force:
                return True

            now = time.monotonic()
            if (
                self._initialized
                and not force
                and now - self._last_init_attempt < self._retry_interval_seconds
            ):
                return False

            self._initialized = True
            self._last_init_attempt = now
            try:
                await asyncio.to_thread(self._initialize_sync)
            except Exception as exc:  # noqa: BLE001
                self.available = False
                self.initialization_error = str(exc)
                logger.warning("RAG服务初始化失败，本次投影将跳过：{}", exc)
                return False

            self.available = True
            self.initialization_error = None
            logger.info(
                "RAG服务初始化成功：collection={}, dimension={}",
                self.collection_name,
                self.embed_dim,
            )
            return True

    def _initialize_sync(self) -> None:
        """同步初始化逻辑，由线程池执行，避免阻塞事件循环。"""
        import chromadb
        from chromadb.config import Settings as ChromaSettings
        from llama_index.core import VectorStoreIndex
        from llama_index.embeddings.openai import OpenAIEmbedding
        from llama_index.vector_stores.chroma import ChromaVectorStore

        api_base = settings.EMBEDDING_API_BASE
        api_key = settings.EMBEDDING_API_KEY
        model_name = settings.EMBEDDING_MODEL

        embed_model = OpenAIEmbedding(
            # LlamaIndex 0.12 会校验 ``model`` 枚举，自定义 LM Studio 模型名
            # 通过 ``model_name`` 传入，最终请求仍使用本地模型。
            model="text-embedding-3-small",
            model_name=model_name,
            api_base=api_base,
            api_key=api_key,
            timeout=settings.EMBEDDING_TIMEOUT_SECONDS,
            max_retries=1,
        )
        probe = embed_model.get_text_embedding("向量服务连通性测试")
        embed_dim = len(probe)
        if embed_dim <= 0:
            raise RuntimeError("Embedding服务返回了空向量")

        model_fingerprint = hashlib.sha256(
            f"{api_base}|{model_name}|{embed_dim}".encode("utf-8")
        ).hexdigest()[:10]
        base_name = re.sub(r"[^A-Za-z0-9._-]", "-", settings.CHROMA_COLLECTION_NAME)
        base_name = base_name.strip("._-") or "novel-embeddings"
        collection_name = f"{base_name}-{embed_dim}-{model_fingerprint}"

        chroma_path = settings.CHROMA_DB_PATH
        os.makedirs(chroma_path, exist_ok=True)
        client = chromadb.PersistentClient(
            path=chroma_path,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        collection = client.get_or_create_collection(
            name=collection_name,
            metadata={
                "description": "小说内容向量投影",
                "embedding_model": model_name,
                "embedding_dimension": embed_dim,
                "embedding_fingerprint": model_fingerprint,
            },
        )
        vector_store = ChromaVectorStore(chroma_collection=collection)

        # 从持久向量库恢复索引句柄；重启后无需先写入即可检索。
        index = VectorStoreIndex.from_vector_store(
            vector_store,
            embed_model=embed_model,
        )

        self.embed_model = embed_model
        self.embed_dim = embed_dim
        self.collection = collection
        self.vector_store = vector_store
        self.index = index
        self.collection_name = collection_name

    @staticmethod
    def _source_key(novel_id: int, chapter: int, metadata: Dict[str, Any]) -> str:
        """用不可复用生命周期生成来源键，数据库整数主键只用于诊断。"""
        source = str(metadata.get("source") or "chapter")
        novel_lifecycle = str(metadata.get("_novel_lifecycle") or "")
        source_lifecycle = str(metadata.get("_source_lifecycle") or "")
        if not novel_lifecycle or not source_lifecycle:
            return f"invalid-novel-{novel_id}-{source}-{chapter}"
        return f"novel-{novel_lifecycle}-{source}-{source_lifecycle}"

    @staticmethod
    def _content_hash(content: str) -> str:
        """生成数据库正文与后台任务之间的稳定内容指纹。"""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _open_session():
        """延迟导入会话工厂，避免模型注册阶段产生循环依赖。"""
        from app.db.base import SessionLocal

        return SessionLocal()

    @classmethod
    def _novel_truth_from_session(cls, db, novel_id: int) -> Optional[NovelProjectionTruth]:
        from app.models.novel import Novel

        novel = db.query(Novel).filter(Novel.id == novel_id).first()
        if novel is None or not novel.rag_lifecycle_id:
            return None
        worldview = novel.worldview or ""
        return NovelProjectionTruth(
            novel_id=novel.id,
            owner_id=novel.user_id,
            lifecycle_id=novel.rag_lifecycle_id,
            rag_revision=int(novel.rag_revision or 1),
            worldview_hash=cls._content_hash(worldview),
        )

    @classmethod
    def _source_truth_from_session(
        cls,
        db,
        novel_id: int,
        source: str,
        chapter_id: Optional[int] = None,
    ) -> Optional[SourceProjectionTruth]:
        novel_truth = cls._novel_truth_from_session(db, novel_id)
        if novel_truth is None:
            return None

        if source == "worldview":
            metadata = {
                "source": source,
                "_novel_lifecycle": novel_truth.lifecycle_id,
                "_source_lifecycle": novel_truth.lifecycle_id,
            }
            return SourceProjectionTruth(
                novel_id=novel_id,
                owner_id=novel_truth.owner_id,
                novel_lifecycle_id=novel_truth.lifecycle_id,
                source=source,
                source_lifecycle_id=novel_truth.lifecycle_id,
                source_key=cls._source_key(novel_id, 0, metadata),
                version=novel_truth.rag_revision,
                content_hash=novel_truth.worldview_hash,
            )

        if source != "chapter" or chapter_id is None:
            return None

        from app.models.novel import Chapter

        chapter = (
            db.query(Chapter)
            .filter(Chapter.id == chapter_id, Chapter.novel_id == novel_id)
            .first()
        )
        if chapter is None or not chapter.rag_lifecycle_id:
            return None
        metadata = {
            "source": source,
            "_novel_lifecycle": novel_truth.lifecycle_id,
            "_source_lifecycle": chapter.rag_lifecycle_id,
        }
        return SourceProjectionTruth(
            novel_id=novel_id,
            owner_id=novel_truth.owner_id,
            novel_lifecycle_id=novel_truth.lifecycle_id,
            source=source,
            source_lifecycle_id=chapter.rag_lifecycle_id,
            source_key=cls._source_key(novel_id, chapter.chapter_number, metadata),
            version=int(chapter.version or 1),
            content_hash=cls._content_hash(chapter.content or ""),
            chapter_id=chapter.id,
            chapter_number=chapter.chapter_number,
        )

    def _load_source_truth_sync(
        self,
        novel_id: int,
        source: str,
        chapter_id: Optional[int] = None,
    ) -> Optional[SourceProjectionTruth]:
        db = self._open_session()
        try:
            return self._source_truth_from_session(db, novel_id, source, chapter_id)
        finally:
            db.close()

    def _load_novel_truth_sync(self, novel_id: int) -> Optional[NovelProjectionTruth]:
        db = self._open_session()
        try:
            return self._novel_truth_from_session(db, novel_id)
        finally:
            db.close()

    @staticmethod
    def _source_token(truth: SourceProjectionTruth) -> Dict[str, Any]:
        return {
            "_novel_lifecycle": truth.novel_lifecycle_id,
            "_owner_id": truth.owner_id,
            "_source_lifecycle": truth.source_lifecycle_id,
        }

    def prepare_novel_projection(self, novel_id: int, db=None) -> Dict[str, Any]:
        """读取数据库持久身份；该方法不再创建进程内生命周期。"""
        owns_session = db is None
        session = db or self._open_session()
        try:
            truth = self._novel_truth_from_session(session, novel_id)
            if truth is None:
                return {}
            return {
                "_novel_lifecycle": truth.lifecycle_id,
                "_owner_id": truth.owner_id,
            }
        finally:
            if owns_session:
                session.close()

    def prepare_chapter_projection(
        self,
        novel_id: int,
        chapter_id: int,
        db=None,
    ) -> Dict[str, Any]:
        """返回章节当前数据库生命周期，后台任务只能写入这一身份。"""
        owns_session = db is None
        session = db or self._open_session()
        try:
            truth = self._source_truth_from_session(
                session,
                novel_id,
                "chapter",
                chapter_id,
            )
            return self._source_token(truth) if truth else {}
        finally:
            if owns_session:
                session.close()

    def prepare_worldview_projection(self, novel_id: int, db=None) -> Dict[str, Any]:
        """返回世界观当前数据库生命周期。"""
        owns_session = db is None
        session = db or self._open_session()
        try:
            truth = self._source_truth_from_session(session, novel_id, "worldview")
            return self._source_token(truth) if truth else {}
        finally:
            if owns_session:
                session.close()

    def mark_chapter_deleted(
        self,
        novel_id: int,
        chapter_id: int,
        db=None,
    ) -> Dict[str, Any]:
        """删除前捕获不可复用的章节身份，供迟到清理精确使用。"""
        owns_session = db is None
        session = db or self._open_session()
        try:
            truth = self._source_truth_from_session(
                session,
                novel_id,
                "chapter",
                chapter_id,
            )
            if truth is None:
                return {}
            return {**self._source_token(truth), "source_key": truth.source_key}
        finally:
            if owns_session:
                session.close()

    def mark_novel_deleted(self, novel_id: int, db=None) -> Dict[str, Any]:
        """删除前捕获小说作者与生命周期，主键复用后令牌不会指向新作品。"""
        return self.prepare_novel_projection(novel_id, db=db)

    def _delete_where_sync(self, where: Dict[str, Any]) -> int:
        """直接从 Chroma 幂等删除满足条件的向量。"""
        if self.collection is None:
            return 0
        result = self.collection.get(where=where)
        ids = list(result.get("ids") or []) if result else []
        if ids:
            self.collection.delete(ids=ids)
        return len(ids)

    def _resolve_index_truth_sync(
        self,
        novel_id: int,
        chapter: int,
        content: str,
        metadata: Dict[str, Any],
    ) -> Optional[SourceProjectionTruth]:
        """写入前用持久身份、版本和内容指纹校验后台任务。"""
        source = str(metadata.get("source") or "chapter")
        chapter_id = metadata.get("chapter_id") if source == "chapter" else None
        if source == "chapter":
            try:
                chapter_id = int(chapter_id)
            except (TypeError, ValueError):
                return None

        # 缺少生命周期的旧后台任务一律失败关闭，防止升级后复活已删除数据。
        required_keys = ("_novel_lifecycle", "_owner_id", "_source_lifecycle")
        if any(metadata.get(key) in (None, "") for key in required_keys):
            return None

        truth = self._load_source_truth_sync(novel_id, source, chapter_id)
        if truth is None:
            return None
        try:
            expected_owner = int(metadata["_owner_id"])
            expected_version = int(metadata.get("version") or 0)
        except (TypeError, ValueError):
            return None
        if (
            str(metadata["_novel_lifecycle"]) != truth.novel_lifecycle_id
            or expected_owner != truth.owner_id
            or str(metadata["_source_lifecycle"]) != truth.source_lifecycle_id
            or expected_version != truth.version
            or chapter != truth.chapter_number
            or self._content_hash(content) != truth.content_hash
        ):
            return None
        return truth

    def _projection_is_current_sync(self, expected: SourceProjectionTruth) -> bool:
        """写入后再次校验数据库，覆盖索引期间发生的更新或删除。"""
        current = self._load_source_truth_sync(
            expected.novel_id,
            expected.source,
            expected.chapter_id,
        )
        return current == expected

    def _cleanup_across_collections_sync(self, where_filters: List[Dict[str, Any]]) -> int:
        """不依赖模型服务，扫描本项目全部embedding集合并幂等清理。"""
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        client = chromadb.PersistentClient(
            path=settings.CHROMA_DB_PATH,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        base_name = re.sub(r"[^A-Za-z0-9._-]", "-", settings.CHROMA_COLLECTION_NAME)
        base_name = base_name.strip("._-") or "novel-embeddings"

        deleted_ids = set()
        for listed_collection in client.list_collections():
            collection_name = (
                listed_collection
                if isinstance(listed_collection, str)
                else listed_collection.name
            )
            if collection_name != base_name and not collection_name.startswith(f"{base_name}-"):
                continue
            collection = (
                client.get_collection(collection_name)
                if isinstance(listed_collection, str)
                else listed_collection
            )
            collection_ids = set()
            for where in where_filters:
                result = collection.get(where=where)
                collection_ids.update(result.get("ids") or [])
            if collection_ids:
                collection.delete(ids=list(collection_ids))
                deleted_ids.update(f"{collection_name}:{item_id}" for item_id in collection_ids)
        return len(deleted_ids)

    async def index_content(
        self,
        novel_id: int,
        chapter: int,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """按数据库真源写入版本化分块，并在写入后再次执行持久栅栏。"""
        if not await self.initialize():
            return False

        from llama_index.core import Document

        metadata = dict(metadata or {})
        try:
            truth = await asyncio.to_thread(
                self._resolve_index_truth_sync,
                novel_id,
                chapter,
                content,
                metadata,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "校验RAG数据库真源失败：novel_id={}, chapter={}, error={}",
                novel_id,
                chapter,
                exc,
            )
            return False
        if truth is None:
            logger.info(
                "跳过已过期或身份不完整的RAG任务：novel_id={}, chapter={}, version={}",
                novel_id,
                chapter,
                metadata.get("version"),
            )
            return True

        source_key = truth.source_key
        version = truth.version
        content_hash = truth.content_hash
        projection_id = hashlib.sha256(
            f"{source_key}|{version}|{content_hash}".encode("utf-8")
        ).hexdigest()[:24]
        chunks = self._split_text(content, chunk_size=500)

        documents = []
        for chunk_index, chunk in enumerate(chunks):
            document_metadata = {
                **metadata,
                "novel_id": novel_id,
                "chapter": chapter,
                "chunk_index": chunk_index,
                "source_key": source_key,
                "version": version,
                "_novel_lifecycle": truth.novel_lifecycle_id,
                "_owner_id": truth.owner_id,
                "_source_lifecycle": truth.source_lifecycle_id,
                "_content_hash": content_hash,
                "_projection_id": projection_id,
            }
            documents.append(
                Document(
                    text=chunk,
                    metadata=document_metadata,
                    id_=f"{source_key}-{projection_id}-chunk-{chunk_index}",
                )
            )

        def write_projection() -> None:
            # 只替换完全相同的投影，不删除未来版本；跨进程乱序由后置栅栏兜底。
            self._delete_where_sync({"_projection_id": projection_id})
            for document in documents:
                self.index.insert(document)

        try:
            novel_lock = self._novel_locks.setdefault(novel_id, asyncio.Lock())
            source_lock = self._source_locks.setdefault(source_key, asyncio.Lock())
            async with novel_lock:
                async with source_lock:
                    await asyncio.to_thread(write_projection)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "索引内容失败：novel_id={}, chapter={}, error={}",
                novel_id,
                chapter,
                exc,
            )
            return False

        try:
            still_current = await asyncio.to_thread(
                self._projection_is_current_sync,
                truth,
            )
            if not still_current:
                await asyncio.to_thread(
                    self._delete_where_sync,
                    {"_projection_id": projection_id},
                )
                logger.info(
                    "已撤销写入期间过期的RAG投影：novel_id={}, chapter={}, version={}",
                    novel_id,
                    chapter,
                    version,
                )
                return True

            # 仅清理严格更旧版本；即使未来版本并发写入，也不会被本任务误删。
            await asyncio.to_thread(
                self._delete_where_sync,
                {
                    "$and": [
                        {"source_key": source_key},
                        {"version": {"$lt": version}},
                    ]
                },
            )
        except Exception as exc:  # noqa: BLE001
            # 无法完成后置校验时删除本次投影，避免以不确定状态参与召回。
            try:
                await asyncio.to_thread(
                    self._delete_where_sync,
                    {"_projection_id": projection_id},
                )
            except Exception:  # noqa: BLE001
                pass
            logger.error(
                "RAG写入后置校验失败：novel_id={}, chapter={}, error={}",
                novel_id,
                chapter,
                exc,
            )
            return False

        if not chunks:
            logger.info(
                "来源内容为空，已清理旧版RAG投影：novel_id={}, chapter={}, version={}",
                novel_id,
                chapter,
                version,
            )

        logger.info(
            "索引内容完成：novel_id={}, chapter={}, version={}, chunks={}",
            novel_id,
            chapter,
            version,
            len(chunks),
        )
        return True

    def _filter_current_nodes_sync(
        self,
        expected_novel: NovelProjectionTruth,
        nodes: List[Any],
    ) -> List[Any]:
        """按数据库当前版本过滤召回结果，崩溃遗留的旧向量也不可见。"""
        db = self._open_session()
        try:
            current_novel = self._novel_truth_from_session(db, expected_novel.novel_id)
            if current_novel != expected_novel:
                return []

            chapter_ids = set()
            for node in nodes:
                metadata = getattr(node, "metadata", {}) or {}
                if metadata.get("source") == "chapter":
                    try:
                        chapter_ids.add(int(metadata.get("chapter_id")))
                    except (TypeError, ValueError):
                        continue

            from app.models.novel import Chapter

            chapters = {}
            if chapter_ids:
                chapters = {
                    chapter.id: chapter
                    for chapter in (
                        db.query(Chapter)
                        .filter(
                            Chapter.novel_id == expected_novel.novel_id,
                            Chapter.id.in_(chapter_ids),
                        )
                        .all()
                    )
                }

            current_nodes = []
            for node in nodes:
                metadata = getattr(node, "metadata", {}) or {}
                if (
                    str(metadata.get("_novel_lifecycle") or "")
                    != expected_novel.lifecycle_id
                    or int(metadata.get("_owner_id") or 0) != expected_novel.owner_id
                ):
                    continue

                source = metadata.get("source")
                if source == "worldview":
                    if (
                        str(metadata.get("_source_lifecycle") or "")
                        == expected_novel.lifecycle_id
                        and int(metadata.get("version") or 0)
                        == expected_novel.rag_revision
                        and str(metadata.get("_content_hash") or "")
                        == expected_novel.worldview_hash
                    ):
                        current_nodes.append(node)
                    continue

                if source != "chapter":
                    continue
                try:
                    chapter_id = int(metadata.get("chapter_id"))
                except (TypeError, ValueError):
                    continue
                chapter = chapters.get(chapter_id)
                if chapter is None:
                    continue
                if (
                    str(metadata.get("_source_lifecycle") or "")
                    == chapter.rag_lifecycle_id
                    and int(metadata.get("version") or 0) == int(chapter.version or 1)
                    and int(metadata.get("chapter") or 0) == chapter.chapter_number
                    and str(metadata.get("_content_hash") or "")
                    == self._content_hash(chapter.content or "")
                ):
                    current_nodes.append(node)
            return current_nodes
        finally:
            db.close()

    async def hybrid_search(self, query: RAGQuery, *, actor_id: int | None = None, novel_lifecycle_id: str | None = None) -> RAGResponse:
        """按作者、作品生命周期和章节范围检索，并回查数据库当前版本。"""
        if not await self.initialize():
            return RAGResponse(query=query.query, results=[], retrieval_method="vector_metadata", status="unavailable", reason="检索服务或来源暂不可用")

        try:
            novel_truth = await asyncio.to_thread(
                self._load_novel_truth_sync,
                query.novel_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("读取RAG小说生命周期失败：novel_id={}, error={}", query.novel_id, exc)
            return RAGResponse(query=query.query, results=[], retrieval_method="vector_metadata", status="unavailable", reason="检索服务或来源暂不可用")
        if novel_truth is None:
            return RAGResponse(query=query.query, results=[], retrieval_method="vector_metadata", status="unavailable", reason="检索服务或来源暂不可用")

        if ((actor_id is not None and novel_truth.owner_id != actor_id)
                or (novel_lifecycle_id is not None and novel_truth.lifecycle_id != novel_lifecycle_id)):
            raise ValueError("检索作品作用域已改变")

        from llama_index.core.vector_stores import (
            FilterCondition,
            FilterOperator,
            MetadataFilter,
            MetadataFilters,
        )

        filters = [
            MetadataFilter(
                key="novel_id",
                value=query.novel_id,
                operator=FilterOperator.EQ,
            ),
            MetadataFilter(
                key="_owner_id",
                value=novel_truth.owner_id,
                operator=FilterOperator.EQ,
            ),
            MetadataFilter(
                key="_novel_lifecycle",
                value=novel_truth.lifecycle_id,
                operator=FilterOperator.EQ,
            ),
        ]
        if query.max_chapter is not None:
            filters.append(
                MetadataFilter(
                    key="chapter",
                    value=query.max_chapter,
                    operator=FilterOperator.LTE,
                )
            )

        try:
            retriever = self.index.as_retriever(
                # 多取少量候选，为数据库版本过滤后的有效结果留出余量。
                similarity_top_k=min(max(query.top_k * 4, query.top_k), 40),
                filters=MetadataFilters(filters=filters, condition=FilterCondition.AND),
            )
            nodes = await asyncio.to_thread(retriever.retrieve, query.query)
            nodes = await asyncio.to_thread(
                self._filter_current_nodes_sync,
                novel_truth,
                nodes,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("RAG检索失败：{}", exc)
            return RAGResponse(query=query.query, results=[], retrieval_method="vector_metadata", status="unavailable", reason="检索服务或来源暂不可用")

        results = []
        for node in nodes[: query.top_k]:
            node_metadata = node.metadata
            results.append(
                RAGResult(
                    content=node.get_content(),
                    metadata={
                        key: value
                        for key, value in node_metadata.items()
                        if key != "novel_id" and not str(key).startswith("_")
                    },
                    score=float(getattr(node, "score", 0.0) or 0.0),
                )
            )

        return RAGResponse(
            query=query.query,
            results=results,
            retrieval_method="vector_metadata",
            status="ready" if results else "empty",
            reason=None if results else "当前范围没有有效的索引结果",
        )

    async def retrieve_worldview(
        self,
        novel_id: int,
        query: str,
        max_chapter: Optional[int] = None,
        *, actor_id: int | None = None, novel_lifecycle_id: str | None = None,
    ) -> List[str]:
        """检索与世界观相关的上下文。"""
        response = await self.hybrid_search(
            RAGQuery(
                novel_id=novel_id,
                query=query,
                top_k=3,
                max_chapter=max_chapter,
            ), actor_id=actor_id, novel_lifecycle_id=novel_lifecycle_id,
        )
        return [result.content for result in response.results]

    async def retrieve_character_info(
        self,
        novel_id: int,
        character_name: str,
        max_chapter: Optional[int] = None,
        *, actor_id: int | None = None, novel_lifecycle_id: str | None = None,
    ) -> List[str]:
        """检索角色设定与历史信息。"""
        response = await self.hybrid_search(
            RAGQuery(
                novel_id=novel_id,
                query=f"{character_name}的性格、外貌、背景",
                top_k=3,
                max_chapter=max_chapter,
            ), actor_id=actor_id, novel_lifecycle_id=novel_lifecycle_id,
        )
        return [result.content for result in response.results]

    @staticmethod
    def _split_text(text: str, chunk_size: int = 500) -> List[str]:
        """按固定字符上限切分文本，并忽略纯空白块。"""
        return [
            text[index : index + chunk_size]
            for index in range(0, len(text), chunk_size)
            if text[index : index + chunk_size].strip()
        ]

    async def delete_novel_index(self, novel_id: int) -> bool:
        """兼容旧调用：幂等删除小说的全部向量。"""
        deletion_token = self.mark_novel_deleted(novel_id)
        try:
            await self.cleanup_novel_vectors(
                novel_id,
                deletion_token=deletion_token,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("删除小说索引失败：novel_id={}, error={}", novel_id, exc)
            return False

    async def cleanup_novel_vectors(
        self,
        novel_id: int,
        deletion_token: Optional[Dict[str, Any]] = None,
    ) -> int:
        """按删除前捕获的生命周期清理，绝不按可复用整数主键清理。"""
        try:
            token = deletion_token or self.prepare_novel_projection(novel_id)
            lifecycle_id = str(token.get("_novel_lifecycle") or "")
            owner_id = token.get("_owner_id")
            if not lifecycle_id or owner_id is None:
                logger.info("没有可清理的小说RAG生命周期：novel_id={}", novel_id)
                return 0
            novel_lock = self._novel_locks.setdefault(novel_id, asyncio.Lock())
            async with novel_lock:
                return await asyncio.to_thread(
                    self._cleanup_across_collections_sync,
                    [
                        {
                            "$and": [
                                {"_novel_lifecycle": lifecycle_id},
                                {"_owner_id": int(owner_id)},
                            ]
                        }
                    ],
                )
        except Exception as exc:  # noqa: BLE001
            logger.error("清理小说向量失败：novel_id={}, error={}", novel_id, exc)
            return 0

    async def cleanup_projection_strict(self, kind: str, token: dict) -> int:
        """持久worker专用：失败必须重试，清理只按捕获的作者及生命周期。"""
        if not token.get("_novel_lifecycle") or token.get("_owner_id") is None:
            raise ValueError("缺少投影清理身份")
        filters = [{"_novel_lifecycle": token["_novel_lifecycle"]}, {"_owner_id": int(token["_owner_id"])}]
        if kind == "delete_chapter":
            if not token.get("_source_lifecycle") or not token.get("source_key"):
                raise ValueError("缺少章节清理身份")
            filters.extend([{"_source_lifecycle": token["_source_lifecycle"]}, {"source_key": token["source_key"]}])
        elif kind != "delete_novel":
            raise ValueError("未知投影清理操作")
        return await asyncio.to_thread(self._cleanup_across_collections_sync, [{"$and": filters}])

    async def cleanup_novel_graph(self, novel_id: int) -> int:
        """图谱清理由一致性投影负责；当前没有可清理实现。"""
        logger.info("小说图谱清理尚未启用：novel_id={}", novel_id)
        return 0

    async def cleanup_novel_cache(self, novel_id: int) -> int:
        """当前没有启用独立缓存，因此不伪报清理数量。"""
        logger.info("小说缓存清理无需执行：novel_id={}", novel_id)
        return 0

    async def cleanup_chapter_data(
        self,
        novel_id: int,
        chapter_id: int,
        deletion_token: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """按删除前章节生命周期清理；主键复用不会扩大清理范围。"""
        try:
            token = deletion_token or self.mark_chapter_deleted(novel_id, chapter_id)
            source_key = str(token.get("source_key") or "")
            novel_lifecycle = str(token.get("_novel_lifecycle") or "")
            source_lifecycle = str(token.get("_source_lifecycle") or "")
            if not source_key or not novel_lifecycle or not source_lifecycle:
                logger.info(
                    "没有可清理的章节RAG生命周期：novel_id={}, chapter_id={}",
                    novel_id,
                    chapter_id,
                )
                return True
            novel_lock = self._novel_locks.setdefault(novel_id, asyncio.Lock())
            source_lock = self._source_locks.setdefault(source_key, asyncio.Lock())
            async with novel_lock:
                async with source_lock:
                    await asyncio.to_thread(
                        self._cleanup_across_collections_sync,
                        [
                            {
                                "$and": [
                                    {"source_key": source_key},
                                    {"_novel_lifecycle": novel_lifecycle},
                                    {"_source_lifecycle": source_lifecycle},
                                ]
                            },
                        ],
                    )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "清理章节向量失败：novel_id={}, chapter_id={}, error={}",
                novel_id,
                chapter_id,
                exc,
            )
            return False


# 全局对象本身不访问模型或磁盘，首次真实调用时才初始化。
rag_service = RAGService()
