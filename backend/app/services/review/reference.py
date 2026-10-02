"""从受权的正式账本构造单次检查参考，不缓存第二套正式事实。"""
import re
from sqlalchemy import select
from app.models.novel import Novel
from app.crud.story_bible import get_active_facts_for_generation, get_events_for_generation
from app.services.context.builder import ContextScopeError


def load_consistency_reference(db, *, novel_id, actor_id, novel_lifecycle_id, chapter, current_day):
    scope = db.execute(select(Novel.user_id, Novel.rag_lifecycle_id).where(Novel.id == novel_id)).first()
    if scope is None or scope.user_id != actor_id or scope.rag_lifecycle_id != novel_lifecycle_id:
        raise ContextScopeError('一致性检查作品来源已变化')
    facts = get_active_facts_for_generation(
        db, novel_id, max_chapter=chapter,
        novel_lifecycle_id=novel_lifecycle_id,
    )
    events = get_events_for_generation(db, novel_id, max_chapter=chapter, current_day=None)
    rules, rule_sources, unsupported = {}, [], []
    for fact in facts:
        if getattr(fact, 'source_status', 'ready') != 'ready':
            continue
        if fact.subject == '世界观' and fact.attribute in ('魔法等级上限', '飞行速度上限') and re.fullmatch(r'\d{1,6}', fact.value.strip()):
            value = int(fact.value.strip())
            if fact.attribute in rules and rules[fact.attribute] != value:
                # 两条互相矛盾的正式规则不能擅自取其中一条。
                unsupported.append(fact.attribute)
            else:
                rules[fact.attribute] = value
                rule_sources.append({'kind': 'story_fact', 'id': fact.id, 'attribute': fact.attribute})
        else:
            unsupported.append(f'fact:{fact.id}')
    for attribute in unsupported:
        rules.pop(attribute, None)
    # 只取此前章的已发生事件；未知章事件不能用来否定当前叙事顺序。
    timeline = [(event.story_day, event.description) for event in events if event.chapter is not None and event.chapter < chapter]
    return {'rules': rules, 'timeline': timeline, 'sources': rule_sources,
            'unsupported_facts': unsupported, 'novel_lifecycle_id': novel_lifecycle_id}
