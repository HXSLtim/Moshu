"""结构化记忆的真实并发、迁移保真和数据库拒绝路径。"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.models
from app.db.base import Base, _set_sqlite_pragmas
from app.models.novel import Novel
from app.models.story_memory import StoryEntity, StoryMemoryCommand, StoryMemoryHead, StateCandidate, OutlineNode
from app.models.story_memory_schemas import EntityInput
from app.models.user import User
from app.services.memory import story as memory
from init_db import _alembic_config


def seeded_engine(path):
    engine = create_engine(f'sqlite:///{path}', connect_args={'check_same_thread': False})
    event.listen(engine, 'connect', _set_sqlite_pragmas)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(User(id=1, username='并发作者', email='concurrent@example.com', hashed_password='x'))
        db.commit()
        novel = Novel(id=1, user_id=1, title='同一作品')
        db.add(novel)
        db.commit()
        lifecycle = novel.rag_lifecycle_id
    return engine, lifecycle


@pytest.mark.parametrize('same_request', [False, True])
def test_concurrent_cas_or_replay_has_exactly_one_effect(tmp_path, same_request):
    """两个真实数据库会话竞争同一版本，异请求仅一个生效，同请求返回相同历史结果。"""
    engine, lifecycle = seeded_engine(tmp_path / 'concurrent.db')
    barrier = Barrier(2)
    first_id = uuid4()
    def write(index):
        request = EntityInput(request_id=first_id if same_request or index == 0 else uuid4(),
            expected_version=0, novel_lifecycle_id=lifecycle, name='青霜剑' if same_request else f'人物{index}', kind='item')
        with Session(engine) as db:
            barrier.wait(timeout=5)
            try:
                return memory.execute_command(db, 1, 1, request, 'create_entity', lambda novel: memory.create_entity(db, novel, request))
            except memory.MemoryConflict:
                return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, [0, 1]))
    with Session(engine) as db:
        assert db.query(StoryEntity).count() == db.query(StoryMemoryCommand).count() == 1
        assert db.get(StoryMemoryHead, 1).version == 1
    if same_request:
        assert results[0] == results[1]
    else:
        assert results.count('conflict') == 1
    engine.dispose()


def test_migration_roundtrip_preserves_author_data_and_rejects_invalid_state(tmp_path):
    """升级/回退后作者原文与旧事实逐字段守恒；新表与 ORM 具备相同检查约束。"""
    engine = create_engine(f'sqlite:///{tmp_path / "migration.db"}')
    event.listen(engine, 'connect', _set_sqlite_pragmas)
    config = _alembic_config(engine)
    command.upgrade(config, 'b9e3f5a7c012')
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (id,username,email,hashed_password,is_active) VALUES (1,'作者','migration@example.com','x',1)"))
        connection.execute(text("INSERT INTO novels (id,title,user_id,rag_lifecycle_id) VALUES (1,'原书',1,'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')"))
        connection.execute(text("INSERT INTO chapters (id,novel_id,chapter_number,title,content,version,rag_lifecycle_id) VALUES (1,1,3,'旧章','原文 🗡️\n {不改动}',4,'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb')"))
        connection.execute(text("INSERT INTO story_facts (id,novel_id,subject,attribute,value,chapter_established,status) VALUES (1,1,'林夏','身份','剑客',3,'active')"))
        original = {name: [dict(row) for row in connection.execute(text(f'SELECT * FROM {name}')).mappings()]
                    for name in ('novels', 'chapters', 'story_facts')}
    command.upgrade(config, 'c0f4a6b8d123')
    inspector = inspect(engine)
    for model in (StoryMemoryHead, StoryEntity, OutlineNode, StateCandidate):
        actual = {row['name'] for row in inspector.get_check_constraints(model.__tablename__)}
        expected = {row.name for row in model.__table__.constraints if row.__class__.__name__ == 'CheckConstraint'}
        assert actual == expected
    with engine.begin() as connection:
        upgraded = connection.execute(text('SELECT * FROM story_facts')).mappings().one()
        assert all(upgraded[key] == value for key, value in original['story_facts'][0].items())
        assert upgraded['origin'] == 'author' and upgraded['source_status'] == 'ready'
        assert upgraded['source_refs'] == '[]' and upgraded['entity_id'] is None
        with pytest.raises(IntegrityError):
            connection.execute(text("INSERT INTO story_memory_heads VALUES (1,'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',-1)"))
    command.downgrade(config, 'b9e3f5a7c012')
    assert 'story_entities' not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        for name, rows in original.items():
            assert [dict(row) for row in connection.execute(text(f'SELECT * FROM {name}')).mappings()] == rows
    command.upgrade(config, 'c0f4a6b8d123')
    engine.dispose()


@pytest.mark.parametrize('model, overrides', [
    (StoryEntity, {'name': ' ', 'kind': 'item'}),
    (StoryEntity, {'name': '物品', 'kind': 'unknown'}),
    (OutlineNode, {'kind': 'scene', 'plot_status': 'occurred', 'title': '无位置'}),
    (OutlineNode, {'kind': 'scene', 'plot_status': 'future', 'chapter_number': 3, 'title': '非法分域'}),
    (StateCandidate, {'entity_id': str(uuid4()), 'attribute': 'holder', 'value': '林夏', 'effective_chapter': 0}),
    (StateCandidate, {'entity_id': str(uuid4()), 'attribute': 'holder', 'value': '林夏', 'effective_chapter': 3, 'status': 'confirmed'}),
])
def test_new_tables_reject_invalid_direct_writes(tmp_path, model, overrides):
    """绕过 HTTP 的直接写入同样不能留下空实体、非法分域、无章或虚假确认。"""
    engine, lifecycle = seeded_engine(tmp_path / 'invalid.db')
    with Session(engine) as db:
        db.add(model(novel_id=1, novel_lifecycle_id=lifecycle, **overrides))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        assert db.query(model).count() == 0
    engine.dispose()


@pytest.mark.parametrize('update_sql, marker', [
    ("UPDATE story_facts SET retired_chapter=2, chapter_established=3", 'ck_story_fact_interval'),
    ("UPDATE story_facts SET value=''", 'ck_story_fact_text'),
    ("UPDATE story_events SET story_day=0", 'ck_story_event_day'),
    ("UPDATE story_events SET status='invented'", 'ck_story_event_status'),
])
def test_invalid_legacy_ledger_stops_before_memory_ddl(tmp_path, update_sql, marker):
    """旧账本不合法时预检定位问题，迁移版本和作者原数据保持原样。"""
    engine = create_engine(f'sqlite:///{tmp_path / "preflight.db"}')
    config = _alembic_config(engine)
    command.upgrade(config, 'b9e3f5a7c012')
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO story_facts (id,novel_id,subject,attribute,value,status) VALUES (1,1,'人物','身份','剑客','active')"))
        connection.execute(text("INSERT INTO story_events (id,novel_id,title,description,story_day,status) VALUES (1,1,'相逢','结识同伴',1,'planned')"))
        connection.execute(text(update_sql))
        before = {table: list(connection.execute(text(f'SELECT * FROM {table}'))) for table in ('story_facts', 'story_events')}
    with pytest.raises(ValueError, match=marker):
        command.upgrade(config, 'c0f4a6b8d123')
    assert 'story_entities' not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == 'b9e3f5a7c012'
        for table, rows in before.items():
            assert list(connection.execute(text(f'SELECT * FROM {table}'))) == rows
    engine.dispose()


@pytest.mark.parametrize('column, value', [
    ('status', 'invented'), ('chapter_established', 0), ('retired_chapter', -1), ('version', 0),
    ('entity_id', 'orphan-without-position'), ('value_entity_id', 'not-a-structured-state'),
])
def test_story_fact_database_rejects_illegal_temporal_and_identity_metadata(tmp_path, column, value):
    """直接 SQL 也不能绕过版本、生效位置、实体作用域与状态限制。"""
    from app.models.story_bible import StoryFact
    engine, lifecycle = seeded_engine(tmp_path / 'fact-check.db')
    with Session(engine) as db:
        fact = StoryFact(novel_id=1, subject='人物', attribute='身份', value='剑客')
        db.add(fact)
        db.commit()
        with pytest.raises(IntegrityError):
            db.execute(text(f'UPDATE story_facts SET {column}=:value WHERE id=:id'), {'value': value, 'id': fact.id})
            db.commit()
        db.rollback()
    engine.dispose()
