import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import Cookie, HTTPException
from .db import connect

COOKIE='nutrition_session'

def hash_password(password: str) -> str:
    salt=secrets.token_bytes(16)
    key=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,600_000)
    return f'{base64.b64encode(salt).decode()}${base64.b64encode(key).decode()}'

def check_password(password: str, stored: str) -> bool:
    try:
        salt,key=stored.split('$')
        candidate=hashlib.pbkdf2_hmac('sha256',password.encode(),base64.b64decode(salt),600_000)
        return hmac.compare_digest(candidate,base64.b64decode(key))
    except (ValueError,TypeError):
        return False

def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

async def create_session(user_id: str) -> str:
    token=secrets.token_urlsafe(40)
    exp=(datetime.now(timezone.utc)+timedelta(days=14)).isoformat()
    async with connect() as db:
        await db.execute('INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)',(token_digest(token),user_id,exp))
        await db.commit()
    return token

async def current_user(nutrition_session: str|None=Cookie(default=None)) -> str:
    if not nutrition_session: raise HTTPException(401,'请登录')
    async with connect() as db:
        cur=await db.execute('SELECT user_id,expires_at FROM sessions WHERE token_hash=?',(token_digest(nutrition_session),))
        row=await cur.fetchone()
    if not row or datetime.fromisoformat(row['expires_at'])<=datetime.now(timezone.utc):
        raise HTTPException(401,'登录状态已过期')
    return str(row['user_id'])
