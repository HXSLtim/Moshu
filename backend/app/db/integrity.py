"""结构升级前只读检查归属，拒绝以自动删除修复未知作者数据。"""
from sqlalchemy import inspect, text
from app.db.base import Base


def verify_existing_references(connection):
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    failures = []
    for table in Base.metadata.sorted_tables:
        if table.name not in tables:
            continue
        present = {column['name'] for column in inspector.get_columns(table.name)}
        for fk in table.foreign_keys:
            parent = fk.column.table
            if parent.name not in tables or fk.parent.name not in present:
                continue
            # 标识符只来自受信任ORM模型，所有返回值仅为计数。
            count = connection.execute(text(
                f'SELECT COUNT(*) FROM "{table.name}" c LEFT JOIN "{parent.name}" p '
                f'ON c."{fk.parent.name}" = p."{fk.column.name}" '
                f'WHERE c."{fk.parent.name}" IS NOT NULL AND p."{fk.column.name}" IS NULL'
            )).scalar_one()
            if count:
                failures.append(f'{table.name}.{fk.parent.name}: {count} 条孤儿')
    if failures:
        raise ValueError('数据库归属预检失败，请先核对并备份，未自动删除数据：' + '; '.join(failures))
