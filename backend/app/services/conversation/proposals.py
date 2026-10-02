"""候选决策命令：作用域、版本与内容校验后在同一事务保存正文和审计。"""
from datetime import datetime
from hashlib import sha256
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.crud import novel as novel_crud
from app.models.novel import Chapter, Novel
from app.models.schemas import ChapterNextCreate, ChapterResponse, ChapterUpdate
from app.models.writing_chat import WritingAdoption, WritingGenerationJob, WritingProposal


def content_hash(content: str) -> str:
    return sha256(content.encode('utf-8')).hexdigest()


def create_proposal(db, *, novel, actor_id, chapter, base_content, operation, content,
                    title=None, turn_id=None, context_manifest=None, execution=None, selection_start=None, selection_end=None):
    from app.services.conversation.jobs import guard_job_publish
    from app.services.context.builder import ContextScopeError, _memory_head_version
    execution_job_id = guard_job_publish(db)
    current_scope = db.execute(select(Novel.user_id, Novel.rag_lifecycle_id).where(Novel.id == novel.id)).first()
    if current_scope is None or current_scope.user_id != actor_id or current_scope.rag_lifecycle_id != novel.rag_lifecycle_id:
        raise HTTPException(409, '小说来源已变化，不能保存候选')
    scope = context_manifest.get('scope', {}) if isinstance(context_manifest, dict) else {}
    # 新的 ContextPack 必须带记忆快照版本；旧接口未提供上下文清单时保留兼容，
    # 由其已有的正文版本和生命周期 CAS 继续保护候选。
    if isinstance(context_manifest, dict) and 'scope' in context_manifest:
        expected_memory = scope.get('memory_head_version')
        if type(expected_memory) is not int:
            raise ContextScopeError('候选缺少记忆快照版本，不能保存候选')
        if _memory_head_version(db, novel.id, novel.rag_lifecycle_id) != expected_memory:
            raise ContextScopeError('结构化记忆已更新，旧上下文候选不能保存，请重新生成')
    # create 的位置基线取创建时点的 max+1:上下文 manifest 的 target_chapter
    # 是检索目标(discuss 轮即当前章),不是创作落章位置,不能当基线。
    target = novel_crud.get_max_chapter_number(db, novel.id) + 1 if operation == 'create' else None
    proposal = WritingProposal(id=str(uuid4()), novel_id=novel.id, actor_id=actor_id,
        novel_lifecycle_id=novel.rag_lifecycle_id, turn_id=turn_id, execution_job_id=execution_job_id,
        chapter_id=chapter.id if chapter else None,
        chapter_lifecycle_id=chapter.rag_lifecycle_id if chapter else None,
        base_version=chapter.version if chapter else 0, base_content_hash=content_hash(base_content),
        operation=operation, target_chapter_number=target, content=content, title=title, selection_start=selection_start, selection_end=selection_end,
        context_manifest=context_manifest, execution=execution)
    db.add(proposal)
    db.flush()
    return proposal


def owned_proposal(db, novel_id, proposal_id, actor_id):
    novel = db.get(Novel, novel_id, populate_existing=True)
    proposal = db.get(WritingProposal, proposal_id, populate_existing=True)
    if (novel is None or novel.user_id != actor_id or proposal is None
            or proposal.novel_id != novel_id or proposal.actor_id != actor_id
            or not proposal.novel_lifecycle_id
            or proposal.novel_lifecycle_id != novel.rag_lifecycle_id):
        raise HTTPException(404, '候选不存在、无权访问或小说来源已改变')
    return proposal


def decide_proposal(db, *, novel_id, proposal_id, actor_id, request_id, decision,
                    expected_version=None, expected_content_hash=None, candidate_content=None):
    """先原子领取待决定候选；任何版本、保存、任务或审计失败都回滚。"""
    if decision not in {'accept', 'reject'}:
        raise HTTPException(422, '不支持的候选决定')
    proposal = owned_proposal(db, novel_id, proposal_id, actor_id)
    previous = db.query(WritingAdoption).filter_by(novel_lifecycle_id=proposal.novel_lifecycle_id, request_id=request_id).first()
    if previous:
        _validate_replay(previous, proposal, decision, expected_version, expected_content_hash, candidate_content)
        return {'proposal': proposal, 'chapter': previous.chapter_snapshot, 'audit_id': previous.id}
    try:
        if decision == 'accept' and proposal.execution_job_id is not None:
            # 与停止入口保持任务→候选的锁顺序；已发布但尚未完成的任务不能被采纳。
            job = db.execute(select(WritingGenerationJob).where(
                WritingGenerationJob.id == proposal.execution_job_id).with_for_update()).scalar_one_or_none()
            if (job is None or job.status != 'completed' or job.actor_id != actor_id
                    or job.novel_lifecycle_id != proposal.novel_lifecycle_id):
                raise HTTPException(409, '候选所属任务尚未成功完成，不能采纳')
        claimed = db.query(WritingProposal).filter_by(id=proposal.id, status='pending').update(
            {'status': 'accepted' if decision == 'accept' else 'rejected', 'decided_at': datetime.utcnow()},
            synchronize_session=False)
        if not claimed:
            db.rollback()
            proposal = owned_proposal(db, novel_id, proposal_id, actor_id)
            previous = db.query(WritingAdoption).filter_by(novel_lifecycle_id=proposal.novel_lifecycle_id, request_id=request_id).first()
            if previous:
                _validate_replay(previous, proposal, decision, expected_version, expected_content_hash, candidate_content)
                return {'proposal': proposal, 'chapter': previous.chapter_snapshot, 'audit_id': previous.id}
            raise HTTPException(409, '候选已经完成决定，请刷新历史')
        db.expire_all()
        proposal = owned_proposal(db, novel_id, proposal_id, actor_id)
        chapter_snapshot = None
        approved_hash = None
        if decision == 'accept':
            if expected_version != proposal.base_version or expected_content_hash != proposal.base_content_hash:
                raise HTTPException(409, '确认请求与候选原文快照不一致，请重新生成')
            chapter = db.execute(select(Chapter).where(Chapter.id == proposal.chapter_id).with_for_update()).scalar_one_or_none() if proposal.chapter_id else None
            if proposal.chapter_id is not None:
                if (chapter is None or chapter.novel_id != novel_id
                        or not proposal.chapter_lifecycle_id
                        or chapter.rag_lifecycle_id != proposal.chapter_lifecycle_id
                        or chapter.version != proposal.base_version
                        or content_hash(chapter.content) != proposal.base_content_hash):
                    raise HTTPException(409, '原文版本、内容或生命周期已变化，请重新生成')
            approved = proposal.content if candidate_content is None else candidate_content
            if not approved.strip():
                raise HTTPException(422, '采纳正文不能为空')
            approved_hash = content_hash(approved)
            if proposal.operation == 'create':
                if proposal.target_chapter_number != novel_crud.get_max_chapter_number(db, novel_id) + 1:
                    raise HTTPException(409, '书中已有新章节，候选的章节位置已变化，请重新生成')
                saved = novel_crud.create_next_chapter(db, novel_id,
                    ChapterNextCreate(title=proposal.title, content=approved), commit=False)
                if saved.chapter_number != proposal.target_chapter_number:
                    raise HTTPException(409, '章节位置在确认时已变化，请重新生成')
            elif proposal.operation in {'append', 'replace', 'replace_selection'} and chapter is not None:
                content = chapter.content + ('\n\n' if chapter.content else '') + approved if proposal.operation == 'append' else approved
                if proposal.operation == 'replace_selection':
                    if (type(proposal.selection_start) is not int or type(proposal.selection_end) is not int
                            or not 0 <= proposal.selection_start < proposal.selection_end <= len(chapter.content)):
                        raise HTTPException(409, '候选选区来源不完整')
                    content = chapter.content[:proposal.selection_start] + approved + chapter.content[proposal.selection_end:]
                if len(content) > 50000:
                    raise HTTPException(422, '采纳后的章节超过50000字符上限，请缩短候选')
                saved = novel_crud.update_chapter(db, chapter.id, ChapterUpdate(
                    content=content, expected_version=proposal.base_version,
                    expected_novel_lifecycle_id=proposal.novel_lifecycle_id,
                    expected_chapter_lifecycle_id=proposal.chapter_lifecycle_id,
                ), commit=False)
            else:
                raise HTTPException(409, '候选操作或来源不支持采纳')
            if saved is None:
                raise HTTPException(409, '候选来源已经不存在')
            db.flush()
            db.refresh(saved)
            chapter_snapshot = ChapterResponse.model_validate(saved).model_dump(mode='json')
            proposal.adopted_chapter_id = saved.id
            proposal.adopted_version = saved.version
        audit = WritingAdoption(id=str(uuid4()), proposal_id=proposal.id, novel_id=novel_id,
            novel_lifecycle_id=proposal.novel_lifecycle_id, actor_id=actor_id, request_id=request_id,
            decision=decision, base_version=proposal.base_version, base_content_hash=proposal.base_content_hash,
            candidate_content_hash=content_hash(proposal.content), approved_content_hash=approved_hash,
            chapter_snapshot=chapter_snapshot)
        db.add(audit)
        db.commit()
        db.refresh(proposal)
        return {'proposal': proposal, 'chapter': chapter_snapshot, 'audit_id': audit.id}
    except novel_crud.ChapterVersionConflictError as exc:
        db.rollback()
        raise HTTPException(409, '原文已被其他编辑更新，请重新生成') from exc
    except novel_crud.ChapterNumberConflictError as exc:
        db.rollback()
        raise HTTPException(409, '章节号正在变化，请重试确认') from exc
    except IntegrityError as exc:
        db.rollback()
        previous = db.query(WritingAdoption).filter_by(novel_lifecycle_id=proposal.novel_lifecycle_id, request_id=request_id).first()
        if previous and previous.proposal_id == proposal_id and previous.decision == decision:
            _validate_replay(previous, owned_proposal(db, novel_id, proposal_id, actor_id), decision, expected_version, expected_content_hash, candidate_content)
            return {'proposal': owned_proposal(db, novel_id, proposal_id, actor_id), 'chapter': previous.chapter_snapshot, 'audit_id': previous.id}
        raise HTTPException(409, '候选已被其他请求处理，请刷新历史') from exc
    except Exception:
        db.rollback()
        raise


def _validate_replay(previous, proposal, decision, expected_version, expected_content_hash, candidate_content):
    if previous.proposal_id != proposal.id or previous.decision != decision:
        raise HTTPException(409, '请求标识已用于其他候选或决定')
    if decision == 'accept' and (expected_version != previous.base_version
            or expected_content_hash != previous.base_content_hash
            or content_hash(proposal.content if candidate_content is None else candidate_content) != previous.approved_content_hash):
        raise HTTPException(409, '重复确认请求的原文版本或采纳正文发生变化')


def _consistency_conflict(db, proposal, novel) -> bool:
    """auto 档守门:对采纳后的正文跑确定性一致性检查,零模型调用。"""
    from app.services.generation.workflow import GenerationWorkflow
    from app.services.review.consistency import consistency_service
    chapter = db.get(Chapter, proposal.chapter_id) if proposal.chapter_id else None
    content = proposal.content
    if proposal.operation == 'append' and chapter is not None:
        content = chapter.content + ('\n\n' if chapter.content else '') + proposal.content
    reference = GenerationWorkflow._load_consistency_reference_sync(
        db, novel.id, novel.user_id, novel.rag_lifecycle_id, None, None)
    result = consistency_service.check_content(
        novel_id=novel.id, content=content,
        chapter=chapter.chapter_number if chapter is not None else 1,
        current_day=None, reference=reference)
    return bool(result.get('has_conflict'))


def auto_apply_pending(bind, novel_id: int, actor_id: int, job_id: str) -> None:
    """任务完成后按作品审核模式自动采纳稿件候选。

    自动采纳复用同一条 decide_proposal 命令:版本 CAS、幂等与采纳审计全部
    保持,审计 request_id 带 ``auto:`` 前缀标识决策来自模式而非人工点击。
    任何失败(守门冲突、版本漂移、校验不通过)都静默留 pending 待作者确认,
    不影响任务本身的完成状态。
    """
    from loguru import logger
    with sessionmaker(bind=bind)() as db:
        try:
            novel = db.get(Novel, novel_id)
            if novel is None or novel.user_id != actor_id or novel.review_mode not in {'auto', 'none'}:
                return
            for proposal in db.query(WritingProposal).filter_by(
                    execution_job_id=job_id, status='pending').all():
                if novel.review_mode == 'auto' and _consistency_conflict(db, proposal, novel):
                    continue
                try:
                    decide_proposal(db, novel_id=novel_id, proposal_id=proposal.id,
                                    actor_id=actor_id, decision='accept',
                                    request_id=f'auto:{proposal.id}',
                                    expected_version=proposal.base_version,
                                    expected_content_hash=proposal.base_content_hash)
                except HTTPException as exc:
                    logger.warning('审核模式自动采纳未通过校验({}),候选保留待确认: {}',
                                   exc.status_code, exc.detail)
        except Exception as exc:  # noqa: BLE001
            logger.warning('审核模式自动采纳检查未完成: {}', exc)
