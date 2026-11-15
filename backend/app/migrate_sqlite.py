"""One-time, explicit, read-only SQLite to an empty MySQL database import.

Run only with the source application stopped and backed up. Never creates or
clears the destination database; a failed import leaves empty schema tables.
"""
import argparse
import asyncio
from datetime import datetime
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from .config import get_settings
from .db import MYSQL_SCHEMA, connect
from .departments import SCHEMA as DEPARTMENT_SCHEMA
from .food_catalog import initialize_catalog
from .meal_estimates import initialize_estimates
from .media_store import initialize_media

TABLES = {
    'users': 'id', 'sessions': 'token_hash', 'mcp_tokens': 'user_id', 'profiles': 'user_id',
    'images': 'id', 'image_payloads': 'image_id', 'foods': 'code',
    'food_metadata': 'food_code', 'food_import_batches': 'id',
    'meals': 'id', 'meal_items': 'id', 'meal_recognitions': 'id',
    'meal_item_estimates': 'meal_item_id', 'chat_messages': 'id',
    'nutrition_reports': 'id', 'hosted_acceptance': 'revision',
    'triage_departments': 'code',
}


def comparable(value):
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d %H:%M:%S')
    return value


async def migrate(source_path: Path, target: str):
    settings = get_settings()
    if target != settings.mysql_database:
        raise ValueError('Target must exactly match configured MYSQL_DATABASE')
    if not source_path.is_file():
        raise ValueError('Source SQLite database does not exist')
    source = sqlite3.connect(source_path.resolve().as_uri() + '?mode=ro', uri=True)
    source.row_factory = sqlite3.Row
    try:
        source.execute('BEGIN')
        auxiliary = list(source.execute("SELECT type, name FROM sqlite_master WHERE type IN ('view', 'trigger')"))
        if auxiliary:
            raise ValueError('Source views or triggers require a custom migration')
        names = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        unexpected = names - TABLES.keys()
        if unexpected:
            raise ValueError('Unsupported source tables: ' + ', '.join(sorted(unexpected)))
        async with connect() as db:
            if await (await db.execute('SHOW TABLES')).fetchone():
                raise ValueError('Target database must be completely empty')

        # MySQL DDL commits automatically. Nothing is removed on failure; an
        # operator must inspect/discard the new target before attempting again.
        async with connect() as db:
            await db.executescript(MYSQL_SCHEMA)
        await initialize_catalog()
        await initialize_estimates()
        await initialize_media(SimpleNamespace(app_image_storage='database'))
        async with connect() as db:
            await db.execute(DEPARTMENT_SCHEMA)
            await db.execute('CREATE TABLE IF NOT EXISTS hosted_acceptance(revision VARCHAR(128) PRIMARY KEY, checked_at VARCHAR(40) NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin')

        counts = {}
        async with connect() as db:
            await db.execute("SET SESSION sql_mode='STRICT_ALL_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO'")
            for table in sorted(names):
                info = list(source.execute(f'PRAGMA table_info(`{table}`)'))
                columns = [row['name'] for row in info]
                target_info = await (await db.execute(f'SHOW COLUMNS FROM `{table}`')).fetchall()
                allowed = {row['Field'] for row in target_info}
                if not set(columns) <= allowed or TABLES[table] not in columns:
                    raise ValueError(f'Unsupported columns or missing primary key in {table}')
                quoted = ','.join(f'`{name}`' for name in columns)
                placeholders = ','.join('?' for _ in columns)
                key = TABLES[table]
                count = 0
                for row in source.execute(f'SELECT {quoted} FROM `{table}`'):
                    values = tuple(row[col] for col in columns)
                    await db.execute(f'INSERT INTO `{table}` ({quoted}) VALUES ({placeholders})', values)
                    imported = await (await db.execute(f'SELECT {quoted} FROM `{table}` WHERE `{key}`=?', (row[key],))).fetchone()
                    if imported is None or any(comparable(imported[col]) != comparable(row[col]) for col in columns):
                        raise ValueError(f'Imported data did not round-trip in {table}')
                    count += 1
                counts[table] = count
            await db.commit()
        return counts
    finally:
        source.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--target', required=True, help='Must match MYSQL_DATABASE; must already exist and contain no tables')
    args = parser.parse_args()
    counts = asyncio.run(migrate(args.source, args.target))
    for name, count in sorted(counts.items()):
        print(f'{name}: {count} rows verified')


if __name__ == '__main__':
    main()
