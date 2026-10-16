"""Lightweight asynchronous SQLite adapter using only Python's standard library."""
import asyncio
import sqlite3
from contextlib import asynccontextmanager
from .config import get_settings

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

class Cursor:
    def __init__(self, cursor): self.cursor=cursor
    async def fetchone(self): return await asyncio.to_thread(self.cursor.fetchone)
    async def fetchall(self): return await asyncio.to_thread(self.cursor.fetchall)

class DB:
    def __init__(self, connection): self.connection=connection
    async def execute(self, sql, params=()):
        return Cursor(await asyncio.to_thread(self.connection.execute, sql, params))
    async def executemany(self, sql, params):
        return await asyncio.to_thread(self.connection.executemany, sql, params)
    async def executescript(self, sql):
        return await asyncio.to_thread(self.connection.executescript, sql)
    async def commit(self): await asyncio.to_thread(self.connection.commit)
    async def rollback(self): await asyncio.to_thread(self.connection.rollback)

@asynccontextmanager
async def connect():
    path=get_settings().app_db_path
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
        await db.executescript(SCHEMA)
        await db.executemany('INSERT OR IGNORE INTO foods(code,name,kcal,protein,fat,carbs) VALUES(?,?,?,?,?,?)',FOODS)
        await db.commit()
