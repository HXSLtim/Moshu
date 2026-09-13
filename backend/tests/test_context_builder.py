"""有效前章简介的作用域、来源、预算与降级契约。"""

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.crud import novel as novel_crud
from app.db.base import Base
from app.models.memory import ChapterDigest, ChapterRevision
from app.models.novel import Chapter, Novel
from app.models.schemas import ChapterUpdate
from app.models.story_bible import StoryEvent, StoryFact
from app.models.story_memory import StoryMemoryHead
from app.models.user import User
from app.services import context_builder
from app.services.chapter_memory import ensure_revision
from app.services.context_budget import (
    MAX_CONTEXT_DIGESTS, MAX_DIGEST_CONTEXT_CHARS, MAX_WORLDVIEW_CONTEXT_CHARS,
    build_writing_chat_messages,
)
from app.services.context_builder import ContextScopeError, build_context_pack
from app.services.digest_extractor import validate_digest
from app.services.memory_config import digest_recipe_version


@pytest.fixture
def context_db():
    """独立内存数据库，无真实模型调用及作者库修改。"""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as db:
        db.add_all([
            User(id=1, username="作者甲", email="a@context.test", hashed_password="unused"),
            User(id=2, username="作者乙", email="b@context.test", hashed_password="unused"),
        ])
        db.commit()
        db.add_all([
            Novel(id=1, user_id=1, title="青霜剑", worldview="作者世界观"),
            Novel(id=2, user_id=2, title="保密作品", worldview="其他作者世界观"),
        ])
        db.commit()
        yield db
    engine.dispose()


def add_digest(db, number=1, *, novel_id=1, summary=None):
    chapter = Chapter(novel_id=novel_id, chapter_number=number,
                      title=f"相遇{number}", content=f"第{number}次相遇，林夏看见青霜剑。")
    db.add(chapter)
    db.flush()
    revision = ensure_revision(db, chapter)
    payload = validate_digest({
        "summary": summary or f"简介{number}：林夏看见青霜剑。",
        "participants": ["候选参与者"], "events": ["候选事件"],
        "state_change_candidates": ["候选持有青霜剑"], "open_threads": ["候选未来决战"],
        "source_refs": [{"quote": chapter.content, "start": 0}],
    }, revision)
    digest = ChapterDigest(novel_id=novel_id, chapter_id=chapter.id,
                           source_revision_id=revision.id, recipe_version=digest_recipe_version(), **payload)
    db.add(digest)
    db.commit()
    return chapter, revision, digest


def build(db, target=2, **overrides):
    args = dict(novel_id=1, actor_id=1,
                novel_lifecycle_id=db.get(Novel, 1).rag_lifecycle_id,
                target_chapter=target)
    args.update(overrides)
    return build_context_pack(db, **args)


@pytest.mark.parametrize("override", [
    {"actor_id": 2}, {"novel_lifecycle_id": "旧生命周期"}, {"novel_id": 999},
    {"target_chapter": 0}, {"target_chapter": True}, {"current_day": 0},
])
def test_scope_errors_never_degrade(context_db, override):
    """身份及时间范围错误不能退化成无简介后继续调用模型。"""
    with pytest.raises(ContextScopeError):
        build(context_db, **override)


def test_scope_reads_database_instead_of_identity_cache(context_db):
    """原生 SQL 改生命周期后，即使 Session 留着旧对象仍拒绝旧身份。"""
    novel = context_db.get(Novel, 1)
    old_lifecycle = novel.rag_lifecycle_id
    context_db.execute(text("UPDATE novels SET rag_lifecycle_id = :value WHERE id = 1"),
                       {"value": "new-lifecycle"})
    with pytest.raises(ContextScopeError):
        build(context_db, novel_lifecycle_id=old_lifecycle)


def test_only_prior_owned_chapters_enter_context_and_manifest(context_db):
    """当前章、未来章和其他作者简介不进入模型或来源清单。"""
    _, revision, digest = add_digest(context_db, 1)
    add_digest(context_db, 2)
    add_digest(context_db, 3)
    add_digest(context_db, 1, novel_id=2, summary="别人的秘密")
    pack = build(context_db, 2)
    assert "简介1" in pack.digest_context
    assert all(value not in pack.digest_context for value in ["简介2", "简介3", "别人的秘密", "候选"])
    assert "自动提取简介，仅作参考，不能替代原文及作者确认设定" in pack.digest_context
    assert pack.manifest["sources"] == [{
        "kind": "chapter_digest", "id": digest.id, "title": "相遇1",
        "chapter_id": revision.chapter_id, "chapter_number": 1,
        "source_revision_id": revision.id, "source_version": 1, "content_hash": revision.content_hash,
    }]
    assert pack.manifest["scope"]["current_day"] is None


def test_context_pack_freezes_memory_head_and_rejects_late_state_change(context_db):
    """模型等待期间作者确认新状态时，旧上下文不能继续产出可采纳候选。"""
    novel = context_db.get(Novel, 1)
    context_db.add(StoryMemoryHead(novel_id=novel.id, novel_lifecycle_id=novel.rag_lifecycle_id, version=3))
    context_db.commit()
    pack = build(context_db)
    assert pack.manifest["scope"]["memory_head_version"] == 3
    context_db.query(StoryMemoryHead).filter_by(novel_id=novel.id).update({"version": 4})
    context_db.commit()
    with pytest.raises(ContextScopeError, match="结构化记忆已更新"):
        context_builder.assert_context_pack_current(
            context_db, pack, novel_id=novel.id, actor_id=novel.user_id,
            novel_lifecycle_id=novel.rag_lifecycle_id,
        )


def test_first_chapter_has_explicit_empty_memory_warning(context_db):
    """首章无前文仍可问答，同时不虚构参考来源。"""
    add_digest(context_db)
    pack = build(context_db, 1)
    assert pack.digest_context == "" and pack.manifest["sources"] == []
    assert any("没有可用" in message for message in pack.manifest["warnings"])


def test_unscoped_legacy_author_fact_is_reported_and_excluded(context_db):
    """未绑定作品生命周期的旧事实不能作为当前作品的高可信上下文。"""
    from app.models.story_memory import StoryEntity
    novel = context_db.get(Novel, 1)
    entity = StoryEntity(novel_id=1, novel_lifecycle_id=novel.rag_lifecycle_id, name='主角', kind='character')
    context_db.add(entity)
    context_db.flush()
    context_db.add_all([StoryFact(novel_id=1, novel_lifecycle_id=novel.rag_lifecycle_id,
        entity_id=entity.id, subject=entity.name, attribute=f'属性{number}', value='有效', chapter_established=1)
        for number in range(41)])
    context_db.add(StoryFact(novel_id=1, subject='世界规则', attribute='能力边界', value='禁止时光倒流'))
    context_db.commit()
    pack = build(context_db)
    assert not any('禁止时光倒流' in entry for entry in pack.story_bible_context)
    assert pack.manifest['omitted']['legacy_unscoped_fact'] == 1
    assert any('未绑定作品生命周期' in warning for warning in pack.manifest['warnings'])
    assert pack.manifest['omitted']['core_state_limit'] == 1
    assert any('核心状态' in warning for warning in pack.manifest['warnings'])


def test_incomplete_core_history_and_outline_window_are_reported(context_db):
    """超出扫描上限时显式报告无法完成历史核验及未扫描的大纲，不能伪装无数据。"""
    from app.models.story_memory import StoryEntity, OutlineNode
    novel = context_db.get(Novel, 1)
    entity = StoryEntity(novel_id=1, novel_lifecycle_id=novel.rag_lifecycle_id, name='主角', kind='character')
    context_db.add(entity)
    context_db.flush()
    context_db.add_all([StoryFact(novel_id=1, novel_lifecycle_id=novel.rag_lifecycle_id,
        entity_id=entity.id, subject=entity.name, attribute=f'属性{number}', value='有效', chapter_established=1)
        for number in range(1001)])
    context_db.add_all([OutlineNode(novel_id=1, novel_lifecycle_id=novel.rag_lifecycle_id,
        kind='chapter', plot_status='occurred', chapter_number=1, title=f'章节结构{number}')
        for number in range(61)])
    context_db.commit()
    pack = build(context_db)
    assert pack.manifest['omitted']['core_scan_window_at_least'] == 1
    assert pack.manifest['omitted']['outline_scan_window_at_least'] == 1
    assert pack.manifest['omitted']['outline_limit'] == 48
    assert not any(row['kind'] == 'core_state' for row in pack.manifest['structured_sources'])
    assert any('历史' in warning for warning in pack.manifest['warnings'])


@pytest.mark.parametrize("table, changes", [
    (ChapterDigest, {"status": "stale"}),
    (ChapterDigest, {"recipe_version": "旧配方"}),
    (ChapterDigest, {"novel_id": 2}),
    (ChapterDigest, {"chapter_id": 999}),
    (ChapterRevision, {"novel_lifecycle_id": "旧作品生命周期"}),
    (ChapterRevision, {"chapter_lifecycle_id": "旧章节生命周期"}),
    (ChapterRevision, {"novel_id": 2}),
    (ChapterRevision, {"version": 2}),
    (ChapterRevision, {"chapter_number": 8}),
    (Chapter, {"title": "绕过版本递增的新标题"}),
    (ChapterRevision, {"content_hash": "0" * 64}),
    (ChapterRevision, {"content": "篡改历史正文"}),
    (Chapter, {"content": "绕过版本递增的新正文"}),
    (Chapter, {"rag_lifecycle_id": "新的章节生命周期"}),
])
def test_stale_or_corrupted_derivations_never_recalled(context_db, table, changes):
    """绕过 ORM 发布守卫的错误归属、旧版本和原文哈希同样在读取时关闭。"""
    chapter, revision, digest = add_digest(context_db)
    record = {Chapter: chapter, ChapterRevision: revision, ChapterDigest: digest}[table]
    context_db.execute(update(table.__table__).where(table.id == record.id).values(**changes))
    context_db.commit()
    pack = build(context_db)
    assert pack.digest_context == "" and pack.manifest["sources"] == []


@pytest.mark.parametrize("changes", [
    {"quote": "原文不存在"}, {"start": 1}, {"start": True}, {"end": 999},
    {"revision_id": "错的版本"}, {"content_hash": "0" * 64}, {"quote_hash": "0" * 64},
])
def test_quote_provenance_is_revalidated(context_db, changes):
    """引用逐字位置、哈希与来源身份均核验，不能只相信 ready 状态。"""
    _, _, digest = add_digest(context_db)
    refs = [dict(digest.source_refs[0], **changes)]
    context_db.execute(update(ChapterDigest).where(ChapterDigest.id == digest.id).values(source_refs=refs))
    context_db.commit()
    pack = build(context_db)
    assert pack.digest_context == ""
    assert pack.manifest["omitted"]["invalid_source"] == 1


@pytest.mark.parametrize("refs", [[], {}, ["错误引用"], [None]])
def test_malformed_reference_structure_is_rejected(context_db, refs):
    """无有效出处的存量数据不进入生成。"""
    _, _, digest = add_digest(context_db)
    context_db.execute(update(ChapterDigest).where(ChapterDigest.id == digest.id).values(source_refs=refs))
    context_db.commit()
    assert build(context_db).manifest["sources"] == []


def test_edit_invalidates_digest_even_if_status_was_not_refreshed(context_db):
    """保存新稿后不再召回旧简介，后续 ready 误写也不能绕过版本保护。"""
    chapter, _, digest = add_digest(context_db)
    novel_crud.update_chapter(context_db, chapter.id, ChapterUpdate(expected_version=1, content="青霜剑不在此地。"))
    context_db.execute(update(ChapterDigest).where(ChapterDigest.id == digest.id).values(status="ready"))
    context_db.commit()
    assert build(context_db).manifest["sources"] == []


def test_recent_digest_budget_manifest_and_fingerprint_match_actual_injection(context_db):
    """有界选择最近三章、按章序呈现，指纹绑定裁剪后实际文本。"""
    for number in range(1, 6):
        add_digest(context_db, number, summary=f"简介{number}：" + "情节" * 800)
    pack = build(context_db, 6)
    assert len(pack.digest_context) <= MAX_DIGEST_CONTEXT_CHARS
    assert len(pack.manifest["sources"]) == MAX_CONTEXT_DIGESTS
    assert [source["chapter_number"] for source in pack.manifest["sources"]] == [3, 4, 5]
    assert pack.digest_context.index("简介3") < pack.digest_context.index("简介4") < pack.digest_context.index("简介5")
    assert pack.manifest["omitted"]["digest_limit"] == 2
    assert pack.manifest["omitted"]["summary_trimmed"] == 3
    assert build(context_db, 6).manifest["fingerprint"] == pack.manifest["fingerprint"]
    newest = pack.manifest["sources"][-1]["id"]
    context_db.execute(update(ChapterDigest).where(ChapterDigest.id == newest).values(
        summary="简介5：" + "情节" * 799 + "结尾",
    ))
    context_db.commit()
    # 预算外的简介尾部没有注入，不能假装影响了本轮上下文身份。
    assert build(context_db, 6).manifest["fingerprint"] == pack.manifest["fingerprint"]
    context_db.execute(update(ChapterDigest).where(ChapterDigest.id == newest).values(summary="变化的简介"))
    context_db.commit()
    assert build(context_db, 6).manifest["fingerprint"] != pack.manifest["fingerprint"]
    messages = build_writing_chat_messages(worldview=pack.worldview, current_content="正文快照",
        story_context="已确认持有物", turns=[], instruction="继续讨论", mode="discuss", digest_context=pack.digest_context)
    system = messages[0][1]
    assert pack.digest_context in system
    assert system.index("【已确认设定】") < system.index("【自动提取的前章简介】") < system.index("【当前编辑正文】")


def test_oversized_direct_chat_digest_cannot_silently_change_sources():
    """包外文本超过预算直接拒绝，不在来源清单生成后再次裁剪。"""
    with pytest.raises(ValueError, match="共享预算"):
        build_writing_chat_messages(worldview="", current_content="", story_context="", turns=[],
            instruction="讨论", mode="discuss", digest_context="字" * (MAX_DIGEST_CONTEXT_CHARS + 1))


def test_candidate_scan_window_is_explicit(context_db, monkeypatch):
    """扫描窗口外数量未知时只报告下界，不伪称遍历整本作品。"""
    for number in range(1, 6):
        add_digest(context_db, number)
    monkeypatch.setattr(context_builder, "MAX_DIGEST_CANDIDATES", 2)
    pack = build(context_db, 6)
    assert [source["chapter_number"] for source in pack.manifest["sources"]] == [4, 5]
    assert pack.manifest["omitted"]["scan_window_at_least"] == 1
    assert any("窗口之外至少 1 条未扫描" in message for message in pack.manifest["warnings"])


def test_story_bible_preserves_temporal_semantics_and_worldview_budget(context_db):
    """简介不晋升事实，正式设定沿用退役区间与已发生事件的时间边界。"""
    novel = context_db.get(Novel, 1)
    novel.worldview = "规则" * 1000
    context_db.add_all([
        StoryFact(novel_id=1, novel_lifecycle_id=novel.rag_lifecycle_id, subject="林夏", attribute="持有物", value="青霜剑", status="retired",
                  chapter_established=1, retired_chapter=4),
        StoryFact(novel_id=1, novel_lifecycle_id=novel.rag_lifecycle_id, subject="林夏", attribute="持有物", value="赤霄剑", status="active", chapter_established=4),
        StoryEvent(novel_id=1, title="确已发生", description="过河", chapter=1, story_day=2, status="occurred"),
        StoryEvent(novel_id=1, title="计划事件", description="尚未过河", chapter=1, story_day=1, status="planned"),
        StoryEvent(novel_id=1, title="无章事件", description="终局", chapter=None, story_day=80, status="occurred"),
    ])
    context_db.commit()
    pack = build(context_db, 3)
    assert len(pack.worldview) == MAX_WORLDVIEW_CONTEXT_CHARS
    confirmed = "\n".join(pack.story_bible_context)
    assert "青霜剑" in confirmed and "确已发生" in confirmed
    assert all(value not in confirmed for value in ["赤霄剑", "计划事件", "无章事件"])
    assert "确已发生" not in "\n".join(build(context_db, 3, current_day=1).story_bible_context)
    assert "无章事件" in "\n".join(build(context_db, 3, current_day=80).story_bible_context)


def test_missing_digest_table_degrades_without_rolling_back_caller(context_db):
    """L1 存储未升级只降级自动简介，外部事务的待写作者数据仍能提交。"""
    context_db.execute(text("DROP TABLE chapter_digests"))
    context_db.commit()
    context_db.get(Novel, 1).title = "待提交的作者标题"
    pack = build(context_db)
    assert pack.manifest["sources"] == []
    assert any("存储暂不可用" in message for message in pack.manifest["warnings"])
    context_db.commit()
    assert context_db.get(Novel, 1).title == "待提交的作者标题"
    assert context_db.execute(text("SELECT 1")).scalar() == 1


def test_story_bible_storage_errors_are_not_disguised_as_missing_memory(context_db):
    """正式设定读取失败必须传播，不能让生成伪装成成功读取过作者真源。"""
    with patch.object(context_builder.story_bible, "get_active_facts_for_generation",
                      side_effect=OperationalError("statement", {}, Exception("不可用"))):
        with pytest.raises(OperationalError):
            build(context_db)


def test_corrupted_json_degrades_inside_savepoint(context_db):
    """JSON 列被外部写坏时，自动简介明确不可用而不使作者写作请求崩溃。"""
    add_digest(context_db)
    context_db.execute(text("UPDATE chapter_digests SET source_refs = 'broken-json'"))
    context_db.commit()
    context_db.get(Novel, 1).title = "保留调用方的修改"
    pack = build(context_db)
    assert not pack.manifest["sources"]
    assert any("存储暂不可用" in warning for warning in pack.manifest["warnings"])
    context_db.commit()
    assert context_db.get(Novel, 1).title == "保留调用方的修改"


@pytest.mark.parametrize("changes", [{"user_id": 2}, {"rag_lifecycle_id": "读取期间已更换"}])
def test_scope_is_rechecked_after_context_read(context_db, monkeypatch, changes):
    """读取多个上下文来源期间换了作者或作品生命周期必须关闭整个调用。"""
    add_digest(context_db)
    original = context_builder._read_digest_candidates

    def replace_scope(*args):
        rows = original(*args)
        context_db.execute(update(Novel.__table__).where(Novel.id == 1).values(**changes))
        return rows

    monkeypatch.setattr(context_builder, "_read_digest_candidates", replace_scope)
    with pytest.raises(ContextScopeError, match="读取期间"):
        build(context_db)
