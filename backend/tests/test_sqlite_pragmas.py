"""SQLite 连接级 PRAGMA 加固回归测试。"""

import threading
import time

from sqlalchemy import create_engine, event, text

from app.db.base import _set_sqlite_pragmas


def _pragmatic_engine(path: str):
    """创建绑定了与主引擎相同 PRAGMA 监听的独立 SQLite 引擎。"""
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )
    event.listen(engine, "connect", _set_sqlite_pragmas)
    return engine


def test_wal_and_busy_timeout_apply_on_connect(tmp_path):
    """连接建立后应处于 WAL 模式并设置等待锁超时。"""
    engine = _pragmatic_engine(str(tmp_path / "pragmas.db"))

    with engine.connect() as connection:
        journal_mode = connection.execute(text("PRAGMA journal_mode")).scalar()
        busy_timeout = connection.execute(text("PRAGMA busy_timeout")).scalar()

    assert journal_mode.lower() == "wal"
    assert busy_timeout == 5000
    engine.dispose()


def test_concurrent_writer_waits_instead_of_locked(tmp_path):
    """一个写者持锁时，另一个写者应等待而非立刻 database is locked。"""
    engine = _pragmatic_engine(str(tmp_path / "writers.db"))
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE counters (id INTEGER PRIMARY KEY, value INTEGER)"))

    holder_entered = threading.Event()
    release_holder = threading.Event()
    holder_committed = threading.Event()

    def holder():
        # engine.begin() 退出时自动提交，锁随之释放。
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO counters (value) VALUES (1)"))
            holder_entered.set()
            # 短暂持锁，让另一个写者在此期间尝试写入。
            release_holder.wait(timeout=5)
        holder_committed.set()

    thread = threading.Thread(target=holder)
    thread.start()
    assert holder_entered.wait(timeout=5)

    started = time.monotonic()
    # 主线程会阻塞在写入上，必须用定时器在持锁期间主动放行，
    # 否则释放动作要等插入完成才执行，双方互相等待到超时。
    timer = threading.Timer(0.3, release_holder.set)
    timer.start()
    try:
        # 主线程在此处写入：旧配置会立刻抛 database is locked，
        # 现在应等待持锁线程释放后在 busy_timeout 内完成。
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO counters (value) VALUES (2)"))
    finally:
        timer.cancel()
        release_holder.set()
    elapsed = time.monotonic() - started

    thread.join(timeout=5)
    assert holder_committed.is_set()
    assert elapsed >= 0.05  # 确实发生过等待，而非绕过锁。
    assert elapsed < 5  # busy_timeout 上限内完成。

    with engine.connect() as connection:
        values = connection.execute(
            text("SELECT value FROM counters ORDER BY id")
        ).scalars().all()
    assert values == [1, 2]
    engine.dispose()
