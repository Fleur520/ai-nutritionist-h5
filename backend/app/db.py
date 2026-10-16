"""Small asynchronous adapter for SQLite development and MySQL deployments."""
import asyncio
import sqlite3
from contextlib import asynccontextmanager
import pymysql
from .config import get_settings

INTEGRITY_ERRORS = (sqlite3.IntegrityError, pymysql.IntegrityError)

FOODS = [
 ('rice','米饭（熟）',116,2.6,.3,25.6),
 ('chicken','鸡胸肉（熟，无皮）',165,31.0,3.6,0),
 ('broccoli','西兰花',34,2.8,.4,6.6),
 ('egg','鸡蛋',144,13.3,8.8,2.8),
 ('apple','苹果',52,.3,.2,13.8),
 ('banana','香蕉',89,1.1,.3,22.8),
 ('noodles','面条（熟）',137,4.5,2.1,25.0),
 ('milk','牛奶（全脂）',61,3.2,3.3,4.8),
 ('tomato','番茄',18,.9,.2,3.9),
 ('potato','土豆（熟）',87,1.9,.1,20.1),
]
SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS profiles(user_id TEXT PRIMARY KEY,name TEXT DEFAULT '',age INTEGER,height_cm REAL,weight_kg REAL,goal TEXT DEFAULT 'balanced');
CREATE TABLE IF NOT EXISTS images(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,path TEXT NOT NULL,mime TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS foods(code TEXT PRIMARY KEY,name TEXT NOT NULL,kcal REAL NOT NULL,protein REAL NOT NULL,fat REAL NOT NULL,carbs REAL NOT NULL);
CREATE TABLE IF NOT EXISTS meals(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,meal_type TEXT NOT NULL,eaten_at TEXT NOT NULL,image_id TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS meal_items(id TEXT PRIMARY KEY,meal_id TEXT NOT NULL,food_code TEXT NOT NULL,grams REAL NOT NULL,kcal REAL NOT NULL,protein REAL NOT NULL,fat REAL NOT NULL,carbs REAL NOT NULL);
CREATE TABLE IF NOT EXISTS chat_messages(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,thread_id TEXT NOT NULL,role TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS nutrition_reports(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,days INTEGER NOT NULL,summary_json TEXT NOT NULL,content TEXT NOT NULL,source TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_reports_user_time ON nutrition_reports(user_id,created_at);
CREATE INDEX IF NOT EXISTS idx_meals_user_time ON meals(user_id,eaten_at);
CREATE INDEX IF NOT EXISTS idx_chat_user_thread ON chat_messages(user_id,thread_id);
"""

# Keep ISO timestamps with offsets as strings: auth and reporting parse these in
# Python. MySQL TIMESTAMP is only used for database-generated creation times.
# MySQL 5.7 has no CREATE INDEX IF NOT EXISTS, so indexes belong to CREATE TABLE.
MYSQL_SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
 id CHAR(36) CHARACTER SET ascii PRIMARY KEY,
 email VARCHAR(254) NOT NULL UNIQUE,password_hash VARCHAR(255) NOT NULL,
 created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS sessions(
 token_hash CHAR(64) CHARACTER SET ascii PRIMARY KEY,
 user_id CHAR(36) CHARACTER SET ascii NOT NULL,expires_at VARCHAR(40) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS profiles(
 user_id CHAR(36) CHARACTER SET ascii PRIMARY KEY,name VARCHAR(60) DEFAULT '',
 age INTEGER,height_cm DOUBLE,weight_kg DOUBLE,goal VARCHAR(20) DEFAULT 'balanced'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS images(
 id CHAR(36) CHARACTER SET ascii PRIMARY KEY,
 user_id CHAR(36) CHARACTER SET ascii NOT NULL,path TEXT NOT NULL,mime VARCHAR(100) NOT NULL,
 created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS foods(
 code VARCHAR(64) CHARACTER SET ascii PRIMARY KEY,name VARCHAR(255) NOT NULL,
 kcal DOUBLE NOT NULL,protein DOUBLE NOT NULL,fat DOUBLE NOT NULL,carbs DOUBLE NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS meals(
 id CHAR(36) CHARACTER SET ascii PRIMARY KEY,
 user_id CHAR(36) CHARACTER SET ascii NOT NULL,meal_type VARCHAR(20) NOT NULL,
 eaten_at VARCHAR(40) NOT NULL,image_id CHAR(36) CHARACTER SET ascii,
 created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
 INDEX idx_meals_user_time(user_id,eaten_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS meal_items(
 id CHAR(36) CHARACTER SET ascii PRIMARY KEY,
 meal_id CHAR(36) CHARACTER SET ascii NOT NULL,food_code VARCHAR(64) CHARACTER SET ascii NOT NULL,
 grams DOUBLE NOT NULL,kcal DOUBLE NOT NULL,protein DOUBLE NOT NULL,
 fat DOUBLE NOT NULL,carbs DOUBLE NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS chat_messages(
 id CHAR(36) CHARACTER SET ascii PRIMARY KEY,
 user_id CHAR(36) CHARACTER SET ascii NOT NULL,thread_id VARCHAR(90) NOT NULL,
 role VARCHAR(20) NOT NULL,content TEXT NOT NULL,
 created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
 INDEX idx_chat_user_thread(user_id,thread_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS nutrition_reports(
 id CHAR(36) CHARACTER SET ascii PRIMARY KEY,
 user_id CHAR(36) CHARACTER SET ascii NOT NULL,days INTEGER NOT NULL,
 summary_json LONGTEXT NOT NULL,content LONGTEXT NOT NULL,source VARCHAR(64) NOT NULL,
 created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
 INDEX idx_reports_user_time(user_id,created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
"""

class Cursor:
    def __init__(self, cursor): self.cursor=cursor
    async def fetchone(self): return await asyncio.to_thread(self.cursor.fetchone)
    async def fetchall(self): return await asyncio.to_thread(self.cursor.fetchall)

class DB:
    def __init__(self, connection, engine='sqlite'):
        self.connection=connection
        self.engine=engine
    async def execute(self, sql, params=()):
        if self.engine == 'mysql':
            def execute():
                cursor=self.connection.cursor()
                try:
                    cursor.execute(sql.replace('?', '%s'),params)
                except BaseException:
                    cursor.close()
                    raise
                return cursor
            return Cursor(await asyncio.to_thread(execute))
        return Cursor(await asyncio.to_thread(self.connection.execute, sql, params))
    async def executemany(self, sql, params):
        if self.engine == 'mysql':
            def executemany():
                with self.connection.cursor() as cursor:
                    return cursor.executemany(sql.replace('?', '%s'),params)
            return await asyncio.to_thread(executemany)
        return await asyncio.to_thread(self.connection.executemany, sql, params)
    async def executescript(self, sql):
        if self.engine == 'mysql':
            # Schema scripts contain only DDL, with no semicolons in literals.
            for statement in sql.split(';'):
                if statement.strip():
                    await self.execute(statement)
            return
        return await asyncio.to_thread(self.connection.executescript, sql)
    async def commit(self): await asyncio.to_thread(self.connection.commit)
    async def rollback(self): await asyncio.to_thread(self.connection.rollback)

@asynccontextmanager
async def connect():
    settings=get_settings()
    if settings.app_db_engine == 'mysql':
        con=await asyncio.to_thread(
            pymysql.connect,host=settings.mysql_host,port=settings.mysql_port,
            user=settings.mysql_user,password=settings.mysql_password,
            database=settings.mysql_database,charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=settings.mysql_connect_timeout,
            read_timeout=30,write_timeout=30,autocommit=False,
            # Match SQLite's UTC CURRENT_TIMESTAMP behavior on every server.
            init_command="SET time_zone = '+00:00'",
        )
        try:
            yield DB(con,'mysql')
        except BaseException:
            await asyncio.to_thread(con.rollback)
            raise
        finally:
            await asyncio.to_thread(con.close)
        return
    path=settings.app_db_path
    path.parent.mkdir(parents=True,exist_ok=True)
    con=await asyncio.to_thread(sqlite3.connect, path.as_posix(), check_same_thread=False,timeout=5)
    con.row_factory=sqlite3.Row
    try:
        await asyncio.to_thread(con.execute, 'PRAGMA foreign_keys=ON')
        await asyncio.to_thread(con.execute, 'PRAGMA journal_mode=WAL')
        await asyncio.to_thread(con.execute, 'PRAGMA busy_timeout=5000')
        yield DB(con)
    finally:
        await asyncio.to_thread(con.close)

async def initialize():
    async with connect() as db:
        await db.executescript(MYSQL_SCHEMA if db.engine == 'mysql' else SCHEMA)
        insert='INSERT IGNORE' if db.engine == 'mysql' else 'INSERT OR IGNORE'
        await db.executemany(insert+' INTO foods(code,name,kcal,protein,fat,carbs) VALUES(?,?,?,?,?,?)',FOODS)
        await db.commit()
