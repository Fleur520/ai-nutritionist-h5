import asyncio
import sqlite3
import uuid

import pymysql
import pytest

from app import db, migrate_sqlite
from app.config import Settings, get_settings


def test_existing_sqlite_requires_explicit_mysql_selection(tmp_path, monkeypatch):
    monkeypatch.delenv('APP_DB_ENGINE', raising=False)
    old = tmp_path / 'old.sqlite3'
    old.touch()
    with pytest.raises(ValueError, match='Existing SQLite data detected'):
        Settings(_env_file=None, app_db_path=old)
    assert Settings(_env_file=None, app_db_path=old, app_db_engine='mysql').app_db_engine == 'mysql'
    with pytest.raises(ValueError):
        Settings(_env_file=None, app_db_engine='sqlite')


def test_sqlite_import_preserves_rows_and_rejects_nonempty_target(tmp_path, monkeypatch):
    settings = get_settings().model_copy()
    name = 'test_migration_' + uuid.uuid4().hex[:16]
    assert name.startswith('test_')
    admin = pymysql.connect(host=settings.mysql_host, port=settings.mysql_port,
                            user=settings.mysql_user, password=settings.mysql_password,
                            ssl=db.mysql_tls(settings), charset='utf8mb4')
    created = False
    try:
        with admin.cursor() as cursor:
            cursor.execute(f'CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin')
        created = True
        settings.mysql_database = name
        monkeypatch.setattr(db, 'get_settings', lambda: settings)
        monkeypatch.setattr(migrate_sqlite, 'get_settings', lambda: settings)
        path = tmp_path / 'source.sqlite3'
        with sqlite3.connect(path) as source:
            source.executescript('''
                CREATE TABLE users(id TEXT PRIMARY KEY,email TEXT,password_hash TEXT,created_at TEXT);
                CREATE TABLE mcp_tokens(user_id TEXT PRIMARY KEY,token_hash TEXT,expires_at TEXT);
                CREATE TABLE foods(code TEXT PRIMARY KEY,name TEXT,kcal REAL,protein REAL,fat REAL,carbs REAL);
                CREATE TABLE food_metadata(food_code TEXT PRIMARY KEY, category TEXT, preparation TEXT, aliases_json TEXT,
                    source_type TEXT, source_model TEXT, batch_id TEXT, basis_g INTEGER, verified INTEGER, created_at TEXT);
                CREATE TABLE image_payloads(image_id TEXT PRIMARY KEY,content BLOB);
            ''')
            source.execute('INSERT INTO users VALUES(?,?,?,?)', ('user-1', 'test@example.com', 'hash', '2026-01-02 03:04:05'))
            source.execute('INSERT INTO mcp_tokens VALUES(?,?,?)', ('user-1', 'token-hash', '2027-01-01T00:00:00+00:00'))
            source.execute('INSERT INTO foods VALUES(?,?,?,?,?,?)', ('food-1', '测试食物', 100.0, 2.0, 1.0, 20.0))
            source.execute('INSERT INTO food_metadata VALUES(?,?,?,?,?,?,?,?,?,?)', ('food-1','谷物','煮熟','[]','ai_estimate','test-model','batch-1',100,0,'2026-01-02 03:04:05'))
            source.execute('INSERT INTO image_payloads VALUES(?,?)', ('image-1', b'\x00\x01image'))
            source.execute('CREATE VIEW food_view AS SELECT * FROM foods')
        with pytest.raises(ValueError, match='views or triggers'):
            asyncio.run(migrate_sqlite.migrate(path, name))
        with sqlite3.connect(path) as source:
            source.execute('DROP VIEW food_view')
        counts = asyncio.run(migrate_sqlite.migrate(path, name))
        assert counts == {'food_metadata': 1, 'foods': 1, 'image_payloads': 1, 'mcp_tokens': 1, 'users': 1}
        async def check():
            async with db.connect() as connection:
                row = await (await connection.execute('SELECT * FROM food_metadata WHERE food_code=?', ('food-1',))).fetchone()
                assert (row['source_type'], row['verified'], row['basis_g'], row['preparation'], row['source_model'], row['batch_id']) == ('ai_estimate',0,100,'煮熟','test-model','batch-1')
                image = await (await connection.execute('SELECT content FROM image_payloads WHERE image_id=?', ('image-1',))).fetchone()
                assert image['content'] == b'\x00\x01image'
        asyncio.run(check())
        with pytest.raises(ValueError, match='completely empty'):
            asyncio.run(migrate_sqlite.migrate(path, name))
        with sqlite3.connect(path) as source:
            assert source.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 1
    finally:
        if created:
            with admin.cursor() as cursor:
                cursor.execute(f'DROP DATABASE `{name}`')
        admin.close()
