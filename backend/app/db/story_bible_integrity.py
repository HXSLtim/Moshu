"""账本约束与升级前只读预检；发现旧数据问题时保留作者记录。"""
from sqlalchemy import inspect, text


STORY_FACT_CHECKS = {
    'ck_story_fact_status': "status IN ('active','retired','revoked')",
    'ck_story_fact_chapter': 'chapter_established IS NULL OR chapter_established > 0',
    'ck_story_fact_retired_chapter': 'retired_chapter IS NULL OR retired_chapter > 0',
    'ck_story_fact_interval': 'chapter_established IS NULL OR retired_chapter IS NULL OR retired_chapter >= chapter_established',
    'ck_story_fact_text': 'length(trim(subject)) > 0 AND length(trim(attribute)) > 0 AND length(trim(value)) > 0',
    'ck_story_fact_version': 'version >= 1',
    'ck_story_fact_origin': "origin IN ('author','ai_confirmed')",
    'ck_story_fact_source_status': "source_status IN ('ready','needs_review')",
    'ck_story_fact_entity_scope': 'entity_id IS NULL OR (novel_lifecycle_id IS NOT NULL AND length(novel_lifecycle_id) = 32 AND chapter_established IS NOT NULL)',
    'ck_story_fact_value_entity': 'value_entity_id IS NULL OR entity_id IS NOT NULL',
    'ck_story_fact_ai_entity': "origin != 'ai_confirmed' OR entity_id IS NOT NULL",
}
STORY_EVENT_CHECKS = {
    'ck_story_event_status': "status IN ('planned','occurred')",
    'ck_story_event_day': 'story_day > 0',
    'ck_story_event_chapter': 'chapter IS NULL OR chapter > 0',
    'ck_story_event_text': 'length(trim(title)) > 0 AND length(trim(description)) > 0',
}


def preflight_story_bible(connection):
    """只扫描当前已有列；扩展列在升级时由确定默认值初始化。"""
    inspector = inspect(connection)
    present_tables = set(inspector.get_table_names())
    failures = []
    required = {
        'story_facts': ('novel_id', 'subject', 'attribute', 'value', 'status', 'origin', 'source_refs', 'source_status', 'version'),
        'story_events': ('novel_id', 'title', 'description', 'story_day', 'status'),
    }
    for table, constraints in (('story_facts', STORY_FACT_CHECKS), ('story_events', STORY_EVENT_CHECKS)):
        if table not in present_tables:
            continue
        columns = {column['name'] for column in inspector.get_columns(table)}
        for name in required[table]:
            if name not in columns:
                continue
            count = connection.execute(text(f'SELECT COUNT(*) FROM {table} WHERE {name} IS NULL')).scalar_one()
            if count:
                failures.append(f'{table}.{name}: {count} 条空值')
        for name, expression in constraints.items():
            # 扩展字段检查由其出现与否决定；所有 SQL 标识符均来自固定领域定义。
            missing = any(field not in columns and field in expression for field in (
                'entity_id', 'novel_lifecycle_id', 'value_entity_id', 'origin', 'source_status', 'version'))
            if missing:
                continue
            count = connection.execute(text(f'SELECT COUNT(*) FROM {table} WHERE NOT ({expression})')).scalar_one()
            if count:
                failures.append(f'{table}.{name}: {count} 条不符合约束')
    if failures:
        raise ValueError('账本升级预检失败，请先核对并备份；未自动修改作者记录：' + '; '.join(failures))
