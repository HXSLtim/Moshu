"""旧数据预检与运行连接外键约束。"""
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from app.db.base import Base, _set_sqlite_pragmas
from app.db.integrity import verify_existing_references
import app.models


def test_app_connection_rejects_orphan_insert(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path / "fk.db"}')
    event.listen(engine, 'connect', _set_sqlite_pragmas)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        assert connection.exec_driver_sql('PRAGMA foreign_keys').scalar_one() == 1
        with pytest.raises(IntegrityError):
            connection.execute(text("INSERT INTO novels(title,user_id,rag_lifecycle_id) VALUES ('无主作品',9,'11111111111111111111111111111111')"))
    engine.dispose()


def test_preflight_does_not_delete_legacy_orphans(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path / "legacy-orphan.db"}')
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO novels(title,user_id,rag_lifecycle_id) VALUES ('孤儿原文',9,'11111111111111111111111111111111')"))
    with engine.connect() as connection:
        with pytest.raises(ValueError, match='novels.user_id'):
            verify_existing_references(connection)
        assert connection.execute(text('SELECT title FROM novels')).scalar_one() == '孤儿原文'
    engine.dispose()
