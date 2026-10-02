"""作者确认的结构化记忆命令；StoryFact 是唯一正式状态来源。"""
import hashlib
import json
from datetime import datetime
from sqlalchemy import update, or_

from app.models.memory import ChapterRevision
from app.models.novel import Novel, Chapter
from app.models.story_bible import StoryFact
from app.models.story_memory import StoryEntity, OutlineNode, StateCandidate, StoryMemoryHead, StoryMemoryCommand


class MemoryConflict(ValueError):
    """版本、同章状态或重放冲突，需要作者刷新并重新确认。"""


class MemoryScopeError(ValueError):
    """作品、实体或来源不属于本轮作者作用域。"""


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def owned_novel(db, novel_id, actor_id):
    novel = db.query(Novel).populate_existing().filter_by(id=novel_id, user_id=actor_id).first()
    if novel is None:
        raise MemoryScopeError("小说不存在或无权访问")
    return novel


def _owned(db, cls, object_id, novel):
    row = db.query(cls).populate_existing().filter_by(
        id=str(object_id), novel_id=novel.id, novel_lifecycle_id=novel.rag_lifecycle_id,
    ).first()
    if row is None:
        raise MemoryScopeError("记录不存在或不属于当前作品")
    return row


def source_revision(db, novel, revision_id):
    revision = db.query(ChapterRevision).populate_existing().filter_by(id=str(revision_id)).first()
    if revision is None or revision.novel_id != novel.id or revision.novel_lifecycle_id != novel.rag_lifecycle_id:
        raise MemoryScopeError("原文来源不属于当前作品")
    chapter = db.query(Chapter).populate_existing().filter_by(id=revision.chapter_id).first()
    if (chapter is None or chapter.novel_id != novel.id or chapter.rag_lifecycle_id != revision.chapter_lifecycle_id
            or chapter.version != revision.version or chapter.chapter_number != revision.chapter_number
            or chapter.title != revision.title or _hash(chapter.content) != revision.content_hash
            or _hash(revision.content) != revision.content_hash):
        raise MemoryConflict("原文来源已变化，请使用当前版本重新审阅")
    return revision


def validate_sources(db, novel, refs, *, effective_chapter=None):
    if not isinstance(refs, list) or len(refs) > 20:
        raise ValueError("来源引用必须为不超过二十条的列表")
    result = []
    for source in refs:
        ref = source.model_dump(mode="json") if hasattr(source, "model_dump") else source
        revision = source_revision(db, novel, ref["revision_id"])
        quote, start = ref["quote"], ref["start"]
        if (not isinstance(quote, str) or not quote.strip() or len(quote) > 500
                or type(start) is not int or start < 0 or revision.content[start:start + len(quote)] != quote):
            raise ValueError("引用文字与原文位置不一致")
        if effective_chapter is not None and revision.chapter_number > effective_chapter:
            raise ValueError("不能用后续章节作为更早状态的出处")
        normalized = dict(revision_id=revision.id, chapter_id=revision.chapter_id,
                          chapter_number=revision.chapter_number, source_version=revision.version,
                          chapter_lifecycle_id=revision.chapter_lifecycle_id,
                          quote=quote, start=start, end=start + len(quote),
                          content_hash=revision.content_hash, quote_hash=_hash(quote))
        for field in ("chapter_id", "chapter_number", "source_version", "chapter_lifecycle_id",
                      "end", "content_hash", "quote_hash"):
            if field in ref and ref[field] != normalized[field]:
                raise MemoryConflict("引用哈希或位置已变化")
        result.append(normalized)
    return result


def _serialize(row):
    return {column.name: value.isoformat() if isinstance(value, datetime) else value
            for column in row.__table__.columns for value in [getattr(row, column.name)]}


def _fact_query(db, novel):
    return db.query(StoryFact).filter(StoryFact.novel_id == novel.id,
        or_(StoryFact.novel_lifecycle_id.is_(None), StoryFact.novel_lifecycle_id == novel.rag_lifecycle_id))


def snapshot(db, novel, chapter=None):
    head = db.get(StoryMemoryHead, novel.id)
    history = _fact_query(db, novel).filter(StoryFact.entity_id.is_not(None)).order_by(
        StoryFact.chapter_established, StoryFact.id).limit(1001).all()
    entities = db.query(StoryEntity).filter_by(novel_id=novel.id, novel_lifecycle_id=novel.rag_lifecycle_id).order_by(StoryEntity.name).limit(501).all()
    outlines = db.query(OutlineNode).filter_by(novel_id=novel.id, novel_lifecycle_id=novel.rag_lifecycle_id).order_by(OutlineNode.chapter_number, OutlineNode.id).limit(501).all()
    candidates = db.query(StateCandidate).filter_by(novel_id=novel.id, novel_lifecycle_id=novel.rag_lifecycle_id).order_by(StateCandidate.effective_chapter.desc(), StateCandidate.id).limit(501).all()
    warnings = []
    if len(history) > 1000 or len(entities) > 500 or len(outlines) > 500 or len(candidates) > 500:
        warnings.append("列表已达到本次显示上限，请缩小作品规模或使用独立查询；未显示部分不表示不存在。")
    states = get_valid_core_facts(db, novel.id, chapter if chapter is not None else 2_147_483_647, limit=1000)
    if any(not sources_are_current(db, novel, row) for row in [*history, *outlines, *candidates]):
        warnings.append("部分记忆的原文或前置状态已变化，需作者核对；未作为当前确认状态使用。")
    return dict(novel_lifecycle_id=novel.rag_lifecycle_id,
                version=head.version if head and head.novel_lifecycle_id == novel.rag_lifecycle_id else 0,
                entities=[_serialize(row) for row in entities[:500]],
                outline_nodes=[_serialize(row) for row in outlines[:500]],
                states=[_serialize(row) for row in states], state_history=[_serialize(row) for row in history[:1000]],
                candidates=[_serialize(row) for row in candidates[:500]], warnings=warnings)


def execute_command(db, novel_id, actor_id, request, action, operation):
    """先取得作品写锁，再 CAS 和幂等检查，操作、事实及命令结果同事务提交。"""
    novel = owned_novel(db, novel_id, actor_id)
    if request.novel_lifecycle_id != novel.rag_lifecycle_id:
        raise MemoryScopeError("作品生命周期已变化，请重新打开作品")
    body = request.model_dump(mode="json")
    signature = _hash(json.dumps({"action": action, "body": body}, ensure_ascii=False, sort_keys=True))
    try:
        locked = db.execute(update(Novel).where(Novel.id == novel.id, Novel.user_id == actor_id,
            Novel.rag_lifecycle_id == request.novel_lifecycle_id).values(rag_revision=Novel.rag_revision)).rowcount
        if locked != 1:
            raise MemoryScopeError("作品来源已变化")
        existing = db.query(StoryMemoryCommand).filter_by(
            novel_lifecycle_id=novel.rag_lifecycle_id, request_id=str(request.request_id)).first()
        if existing:
            if existing.payload_hash != signature:
                raise MemoryConflict("同一个请求标识不能用于不同命令")
            result = existing.result
            db.commit()
            return result
        head = db.get(StoryMemoryHead, novel.id)
        if head is None:
            head = StoryMemoryHead(novel_id=novel.id, novel_lifecycle_id=novel.rag_lifecycle_id, version=0)
            db.add(head)
            db.flush()
        if head.novel_lifecycle_id != novel.rag_lifecycle_id:
            raise MemoryScopeError("记忆版本不属于当前作品")
        changed = db.execute(update(StoryMemoryHead).where(StoryMemoryHead.novel_id == novel.id,
            StoryMemoryHead.version == request.expected_version).values(version=StoryMemoryHead.version + 1))
        if changed.rowcount != 1:
            raise MemoryConflict("记忆已被更新，请刷新后重新审阅")
        operation(novel)
        db.flush()
        db.refresh(head)
        result = snapshot(db, novel)
        db.add(StoryMemoryCommand(novel_id=novel.id, novel_lifecycle_id=novel.rag_lifecycle_id,
            request_id=str(request.request_id), payload_hash=signature, result=result))
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def create_entity(db, novel, data):
    entity = StoryEntity(novel_id=novel.id, novel_lifecycle_id=novel.rag_lifecycle_id,
        name=data.name, description=data.description, kind=data.kind)
    db.add(entity)
    db.flush()
    return entity


def save_outline(db, novel, data, node_id=None, *, origin="author"):
    parent = _owned(db, OutlineNode, data.parent_id, novel) if data.parent_id else None
    if parent and (parent.plot_status != data.plot_status
                   or {"chapter": "volume", "scene": "chapter"}.get(data.kind) != parent.kind):
        raise ValueError("大纲父子必须同属计划或实际分域，层级应为卷、章、场景")
    if parent and data.kind == "scene" and parent.chapter_number != data.chapter_number:
        raise ValueError("场景必须属于父章节的同一章节号")
    if data.kind != "volume" and data.chapter_number is None:
        raise ValueError("章节和场景大纲必须指定章节号")
    if data.plot_status == "occurred" and not data.source_refs and origin == "ai":
        raise ValueError("AI 实际剧情大纲必须引用原文")
    refs = validate_sources(db, novel, data.source_refs, effective_chapter=data.chapter_number)
    row = _owned(db, OutlineNode, node_id, novel) if node_id else OutlineNode(
        novel_id=novel.id, novel_lifecycle_id=novel.rag_lifecycle_id, origin=origin)
    if parent and parent.id == row.id:
        raise ValueError("大纲不能以自身为父节点")
    if node_id:
        descendants = db.query(OutlineNode).filter_by(parent_id=row.id).all()
        if descendants and (data.plot_status != row.plot_status or data.kind != row.kind):
            raise MemoryConflict("已有子节点时不能改变大纲分域或层级")
        if data.kind == "chapter" and any(child.chapter_number != data.chapter_number for child in descendants):
            raise MemoryConflict("已有场景时不能单独改变父章节号")
        seen = {row.id}
        ancestor = parent
        while ancestor:
            if ancestor.id in seen:
                raise ValueError("大纲不能形成循环")
            seen.add(ancestor.id)
            ancestor = _owned(db, OutlineNode, ancestor.parent_id, novel) if ancestor.parent_id else None
    for field in ("kind", "plot_status", "chapter_number", "title", "conflict", "outcome"):
        setattr(row, field, getattr(data, field))
    row.parent_id = str(data.parent_id) if data.parent_id else None
    row.source_refs, row.source_status = refs, "ready"
    if origin == "author":
        row.origin = "author"
    db.add(row)
    return row


def _validate_state(db, novel, data):
    if (not isinstance(data.attribute, str) or not data.attribute.strip() or len(data.attribute) > 100
            or data.attribute != data.attribute.strip() or not isinstance(data.value, str)
            or not data.value.strip() or len(data.value) > 2000
            or type(data.effective_chapter) is not int or data.effective_chapter <= 0):
        raise ValueError("状态属性、值与生效章节必须符合领域约定")
    entity = _owned(db, StoryEntity, data.entity_id, novel)
    target = _owned(db, StoryEntity, data.value_entity_id, novel) if data.value_entity_id else None
    value = data.value
    if entity.kind == "item" and data.attribute in {"owner", "holder"}:
        if target is None and db.query(StoryEntity.id).filter_by(novel_id=novel.id,
                novel_lifecycle_id=novel.rag_lifecycle_id, name=value).limit(2).count() > 1:
            raise ValueError("存在同名实体，请明确选择所有者或持有者的实体身份")
        if target and target.kind not in {"character", "organization", "location"}:
            raise ValueError("物品所有者或持有者必须是人物、组织或位置实体")
        if target:
            value = target.name
    if data.attribute == "quantity":
        if entity.kind != "item" or not value.isascii() or not value.isdigit() or len(value) > 12 or target:
            raise ValueError("数量必须属于物品，且为不超过十二位的非负整数，不关联另一实体")
        value = str(int(value))
    return entity, value, str(target.id) if target else None


def _timeline(db, novel, entity_id, attribute):
    return _fact_query(db, novel).filter(StoryFact.entity_id == str(entity_id), StoryFact.attribute == attribute,
        StoryFact.status != "revoked").order_by(StoryFact.chapter_established, StoryFact.id).all()


def _rebuild_intervals(db, novel, entity_id, attribute):
    """失效记录仍保留区间边界，避免悄悄恢复已经被剧情替代的旧状态。"""
    db.flush()
    rows = _timeline(db, novel, entity_id, attribute)
    for index, row in enumerate(rows):
        next_chapter = rows[index + 1].chapter_established if index + 1 < len(rows) else None
        row.status = "retired" if next_chapter is not None else "active"
        row.retired_chapter = next_chapter


def _mark_following(db, novel, entity_id, attribute, chapter):
    # 同一物品的所有权、持有与数量互相依赖；保守标记后续实体状态，避免属性之间漏传失效。
    for fact in _fact_query(db, novel).filter(StoryFact.entity_id == str(entity_id), StoryFact.status != "revoked"):
        if fact.chapter_established > chapter:
            fact.source_status = "needs_review"
            fact.version += 1
    for candidate in db.query(StateCandidate).filter_by(novel_lifecycle_id=novel.rag_lifecycle_id,
            entity_id=str(entity_id)).filter(StateCandidate.effective_chapter > chapter):
        candidate.source_status = "needs_review"


def create_state(db, novel, data, *, origin="author"):
    entity, value, target = _validate_state(db, novel, data)
    refs = validate_sources(db, novel, data.source_refs, effective_chapter=data.effective_chapter)
    if origin == "ai_confirmed" and not refs:
        raise ValueError("AI 状态确认必须有当前原文出处")
    if any(fact.chapter_established == data.effective_chapter for fact in _timeline(db, novel, entity.id, data.attribute)):
        raise MemoryConflict("同实体同属性在同一章已有状态，请先撤销旧候选或明确替换状态")
    _mark_following(db, novel, entity.id, data.attribute, data.effective_chapter)
    fact = StoryFact(novel_id=novel.id, novel_lifecycle_id=novel.rag_lifecycle_id,
        entity_id=entity.id, subject=entity.name, attribute=data.attribute, value=value,
        value_entity_id=target, chapter_established=data.effective_chapter,
        origin=origin, source_refs=refs, source_status="ready", status="active")
    db.add(fact)
    _rebuild_intervals(db, novel, entity.id, data.attribute)
    return fact


def create_candidate(db, novel, data):
    entity, value, target = _validate_state(db, novel, data)
    if not data.source_refs:
        raise ValueError("待确认状态必须有原文出处")
    refs = validate_sources(db, novel, data.source_refs, effective_chapter=data.effective_chapter)
    # 不同请求重提同一来源和变化，也不会重复制造待确认候选。
    for existing in db.query(StateCandidate).filter_by(novel_lifecycle_id=novel.rag_lifecycle_id,
            entity_id=entity.id, attribute=data.attribute, value=value, effective_chapter=data.effective_chapter):
        if existing.value_entity_id == target and existing.source_refs == refs:
            return existing
    row = StateCandidate(novel_id=novel.id, novel_lifecycle_id=novel.rag_lifecycle_id,
        entity_id=entity.id, attribute=data.attribute, value=value, value_entity_id=target,
        effective_chapter=data.effective_chapter, source_refs=refs, source_status="ready", status="pending")
    db.add(row)
    db.flush()
    return row


def decide_candidate(db, novel, candidate_id, data):
    from types import SimpleNamespace
    row = _owned(db, StateCandidate, candidate_id, novel)
    if data.action == "confirm":
        if row.status != "pending" or row.source_status != "ready":
            raise MemoryConflict("仅可确认来源仍有效的待审阅候选")
        refs = validate_sources(db, novel, row.source_refs, effective_chapter=row.effective_chapter)
        fact = create_state(db, novel, SimpleNamespace(entity_id=row.entity_id, attribute=row.attribute,
            value=row.value, value_entity_id=row.value_entity_id, effective_chapter=row.effective_chapter,
            source_refs=refs), origin="ai_confirmed")
        row.status, row.fact_id = "confirmed", fact.id
    elif data.action == "reject":
        if row.status != "pending":
            raise MemoryConflict("仅可拒绝待审阅候选")
        row.status = "rejected"
    else:
        if row.status != "confirmed":
            raise MemoryConflict("仅可撤销已确认的候选")
        fact = _fact_query(db, novel).filter_by(id=row.fact_id).first()
        if fact is None or fact.status == "revoked":
            raise MemoryConflict("对应事实已不存在或已撤销")
        fact.status, fact.source_status = "revoked", "needs_review"
        fact.version += 1
        row.status = "revoked"
        _mark_following(db, novel, row.entity_id, row.attribute, row.effective_chapter)
        _rebuild_intervals(db, novel, row.entity_id, row.attribute)
    row.reason = data.reason
    return row


def resolve_source(db, novel, kind, record_id, data):
    if kind == "state":
        row = _fact_query(db, novel).filter_by(id=record_id).first()
        if row is None or not row.entity_id or row.status == "revoked":
            raise MemoryScopeError("可核对状态不存在")
        chapter = row.chapter_established
    else:
        row = _owned(db, OutlineNode, record_id, novel)
        chapter = row.chapter_number
    row.source_refs = validate_sources(db, novel, data.source_refs, effective_chapter=chapter)
    row.source_status = "ready"
    row.origin = "author"
    if kind == "state":
        row.description = data.reason
        row.version += 1
    return row


def replace_state(db, novel, fact_id, data):
    old = _fact_query(db, novel).filter_by(id=fact_id).first()
    if old is None or old.entity_id != str(data.entity_id) or old.attribute != data.attribute or old.status == "revoked":
        raise MemoryScopeError("被替换状态不属于当前实体及属性")
    old.status, old.source_status = "revoked", "needs_review"
    old.version += 1
    _mark_following(db, novel, old.entity_id, old.attribute, min(old.chapter_established, data.effective_chapter))
    for candidate in db.query(StateCandidate).filter_by(novel_lifecycle_id=novel.rag_lifecycle_id, fact_id=old.id, status="confirmed"):
        candidate.status = "revoked"
        candidate.reason = "作者以新的正式状态替换"
    db.flush()
    return create_state(db, novel, data)


def invalidate_chapter_sources(db, chapter, *, deleted=False):
    """在原文保存/删除同事务调用，保留作者内容并标记后续相关依赖。"""
    novel = db.get(Novel, chapter.novel_id)
    if novel is None:
        return
    revisions = db.query(ChapterRevision.id, ChapterRevision.chapter_number).filter_by(
        chapter_lifecycle_id=chapter.rag_lifecycle_id)
    if not deleted:
        revisions = revisions.filter(ChapterRevision.version != chapter.version)
    invalid_revisions = revisions.all()
    invalid_ids = {row.id for row in invalid_revisions}
    if not invalid_ids:
        return
    first_affected_chapter = min(chapter.chapter_number, *(row.chapter_number for row in invalid_revisions))
    changed = False
    affected = []
    def depends(row):
        return any(ref.get("revision_id") in invalid_ids for ref in row.source_refs or [] if isinstance(ref, dict))
    for fact in _fact_query(db, novel).filter(StoryFact.entity_id.is_not(None)):
        if depends(fact):
            fact.source_status = "needs_review"
            fact.version += 1
            affected.append((fact.entity_id, fact.attribute, fact.chapter_established or 1))
            changed = True
    for candidate in db.query(StateCandidate).filter_by(novel_lifecycle_id=novel.rag_lifecycle_id):
        if depends(candidate):
            candidate.source_status = "needs_review"
            changed = True
    for node in db.query(OutlineNode).filter_by(novel_lifecycle_id=novel.rag_lifecycle_id):
        if depends(node) or (node.plot_status == "occurred" and node.source_refs
                            and node.chapter_number is not None and node.chapter_number > first_affected_chapter):
            node.source_status = "needs_review"
            changed = True
    for entity_id, attribute, effective in affected:
        _mark_following(db, novel, entity_id, attribute, effective)
    if changed:
        db.execute(update(StoryMemoryHead).where(StoryMemoryHead.novel_id == novel.id,
            StoryMemoryHead.novel_lifecycle_id == novel.rag_lifecycle_id).values(version=StoryMemoryHead.version + 1))
        db.flush()


def sources_are_current(db, novel, row):
    if row.source_status != "ready":
        return False
    try:
        refs = row.source_refs or []
        if not isinstance(refs, list) or len(refs) > 20:
            return False
        if not refs and (getattr(row, "origin", None) in {"ai", "ai_confirmed"} or isinstance(row, StateCandidate)):
            return False
        if getattr(row, "entity_id", None):
            _owned(db, StoryEntity, row.entity_id, novel)
        if getattr(row, "value_entity_id", None):
            _owned(db, StoryEntity, row.value_entity_id, novel)
        validate_sources(db, novel, refs,
                         effective_chapter=getattr(row, "chapter_established", getattr(row, "chapter_number", None)))
        return True
    except (ValueError, KeyError, TypeError):
        return False


def get_valid_core_facts(db, novel_id, target_chapter, limit=40, *, diagnostics=None):
    """复查来源链，不把失效状态后的后续状态当作无争议真相。"""
    novel = db.get(Novel, novel_id)
    if novel is None:
        return []
    rows = _fact_query(db, novel).filter(StoryFact.entity_id.is_not(None),
        StoryFact.status != "revoked", StoryFact.chapter_established <= target_chapter).order_by(
        StoryFact.chapter_established, StoryFact.id).limit(1001).all()
    if len(rows) > 1000:
        if diagnostics is not None:
            diagnostics["core_scan_window_at_least"] = 1
        return []
    blocked, blocked_entities, current = set(), set(), {}
    for row in rows:
        key = (row.entity_id, row.attribute)
        if not sources_are_current(db, novel, row):
            blocked_entities.add(row.entity_id)
            blocked.add(key)
        # 明确作者重新核验的独立设定不再依赖旧原文。
        elif row.origin == "author" and row.description:
            blocked.discard(key)
        elif row.entity_id in blocked_entities:
            # 即使改稿绕过事务失效传播，后续持有、数量等属性也不能跳过前置冲突。
            blocked.add(key)
        current[key] = row
    valid = [row for key, row in current.items() if key not in blocked
             and (row.retired_chapter is None or target_chapter < row.retired_chapter)]
    if diagnostics is not None:
        if blocked:
            diagnostics["core_unverified_state"] = len(blocked)
        if len(valid) > limit:
            diagnostics["core_state_limit"] = len(valid) - limit
    return valid[:limit]


def get_outline_for_generation(db, novel_id, target_chapter, *, include_plans=False, limit=12, diagnostics=None):
    """计划仅由显式规划任务选择；实际大纲必须有当前出处，人工内容不被重建覆盖。"""
    novel = db.get(Novel, novel_id)
    if novel is None:
        return []
    query = db.query(OutlineNode).filter_by(novel_id=novel.id, novel_lifecycle_id=novel.rag_lifecycle_id)
    if include_plans:
        query = query.filter(or_(OutlineNode.plot_status == "planned", OutlineNode.chapter_number <= target_chapter))
    else:
        query = query.filter(OutlineNode.plot_status == "occurred", OutlineNode.chapter_number <= target_chapter)
    rows = query.order_by(OutlineNode.chapter_number.desc(), OutlineNode.id).limit(61).all()
    valid = [row for row in rows[:60] if sources_are_current(db, novel, row)]
    if diagnostics is not None:
        if len(rows) > 60:
            diagnostics["outline_scan_window_at_least"] = 1
        if len(valid) < min(len(rows), 60):
            diagnostics["outline_invalid_source"] = min(len(rows), 60) - len(valid)
        if len(valid) > limit:
            diagnostics["outline_limit"] = len(valid) - limit
    return valid[:limit]


def publish_extraction(db, novel, revision_id, extraction):
    """发布前再次核对来源；新结果独立追加，不覆盖作者手写大纲。"""
    from types import SimpleNamespace
    revision = source_revision(db, novel, revision_id)
    for item in extraction.states:
        refs = [dict(ref.model_dump(), revision_id=revision.id) for ref in item.source_refs]
        create_candidate(db, novel, SimpleNamespace(**item.model_dump(exclude={"source_refs"}),
            effective_chapter=revision.chapter_number, source_refs=refs))
    # 相同来源与内容复用节点身份；作者编辑过的节点 origin=author 永远保留。
    previous = [row for row in db.query(OutlineNode).filter_by(
        novel_lifecycle_id=novel.rag_lifecycle_id, origin="ai")
        if any(ref.get("revision_id") == revision.id for ref in row.source_refs or [])]
    retained = set()
    for item in extraction.outline:
        refs = [dict(ref.model_dump(), revision_id=revision.id) for ref in item.source_refs]
        normalized = validate_sources(db, novel, refs, effective_chapter=revision.chapter_number)
        existing = next((row for row in previous if row.source_status == "ready"
            and row.source_refs == normalized and all(getattr(row, field) == getattr(item, field)
                for field in ("title", "conflict", "outcome"))), None)
        if existing is None:
            existing = save_outline(db, novel, SimpleNamespace(kind="scene", plot_status="occurred", parent_id=None,
                chapter_number=revision.chapter_number, source_refs=refs,
                **item.model_dump(exclude={"source_refs"})), origin="ai")
            db.flush()
            previous.append(existing)
        retained.add(existing.id)
    for old in previous:
        if old.id not in retained:
            old.source_status = "needs_review"
