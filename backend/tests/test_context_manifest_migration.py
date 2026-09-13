"""上下文来源列升级保留旧对话，旧库分支不得遗漏可空新列。"""
from alembic import command
from sqlalchemy import create_engine, inspect, text

from init_db import initialize_database, _alembic_config


def old_database(tmp_path, name):
    engine = create_engine(f'sqlite:///{tmp_path / name}')
    command.upgrade(_alembic_config(engine), 'a8d2e4f6b901')
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (id,username,email,hashed_password,is_active) VALUES (1,'历史作者','legacy@example.com','unused',1)"))
        connection.execute(text("INSERT INTO novels (id,title,user_id,rag_lifecycle_id,rag_revision) VALUES (1,'历史作品',1,'11111111111111111111111111111111',1)"))
        connection.execute(text("INSERT INTO writing_turns (novel_id,request_id,chapter_id,chapter_title,mode,user_text,assistant_text,base_content_hash,status) VALUES (1,'旧请求',1,'旧章节','discuss','必须保留的问题','必须保留的回答','哈希','completed')"))
    return engine


def test_manifest_upgrade_and_downgrade_preserve_chat_text(tmp_path):
    """列升级/回退均不修改原问答；缺失来源保持 SQL NULL。"""
    engine = old_database(tmp_path, 'managed.db')
    initialize_database(engine)
    with engine.connect() as connection:
        row = connection.execute(text('SELECT user_text,assistant_text,context_manifest FROM writing_turns')).one()
        assert tuple(row) == ('必须保留的问题', '必须保留的回答', None)
    command.downgrade(_alembic_config(engine), 'a8d2e4f6b901')
    assert 'context_manifest' not in {column['name'] for column in inspect(engine).get_columns('writing_turns')}
    with engine.connect() as connection:
        assert connection.execute(text('SELECT assistant_text FROM writing_turns')).scalar() == '必须保留的回答'
    initialize_database(engine)
    engine.dispose()


def test_legacy_existing_chat_table_gets_missing_manifest_column(tmp_path):
    """无 Alembic 历史但已有对话表时，create_all 不能替代补列迁移。"""
    engine = old_database(tmp_path, 'legacy.db')
    with engine.begin() as connection:
        connection.execute(text('DROP TABLE alembic_version'))
    initialize_database(engine)
    initialize_database(engine)
    with engine.connect() as connection:
        row = connection.execute(text('SELECT assistant_text,context_manifest FROM writing_turns')).one()
        assert tuple(row) == ('必须保留的回答', None)
    engine.dispose()
