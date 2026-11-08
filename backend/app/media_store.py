"""Optional database-backed photos for hosts with disposable local disks."""
import asyncio
from pathlib import Path
import uuid

from fastapi import HTTPException

from .db import connect


async def initialize_media(settings):
    if settings.app_image_storage != 'database':
        return
    async with connect() as db:
        column = 'MEDIUMBLOB' if db.engine == 'mysql' else 'BLOB'
        key = 'CHAR(36) CHARACTER SET ascii' if db.engine == 'mysql' else 'TEXT'
        await db.execute(f'CREATE TABLE IF NOT EXISTS image_payloads(image_id {key} PRIMARY KEY, content {column} NOT NULL)')
        await db.commit()


async def image_content(image_id):
    async with connect() as db:
        row = await (await db.execute('SELECT content FROM image_payloads WHERE image_id=?', (image_id,))).fetchone()
    if row is None:
        raise HTTPException(404, '图片不存在')
    return bytes(row['content'])


async def recognition_path(image_id, stored_path, settings):
    if stored_path != 'db:' + image_id:
        path = Path(stored_path).resolve()
        if path.parent != settings.app_media_dir.resolve() or not path.is_file():
            raise HTTPException(404, '图片不存在')
        return path
    try:
        if str(uuid.UUID(image_id)) != image_id:
            raise ValueError('invalid image id')
    except ValueError:
        raise HTTPException(404, '图片不存在') from None
    path = settings.app_media_dir.resolve() / (image_id + '.jpg')
    if not path.is_file():
        content = await image_content(image_id)
        def restore():
            settings.app_media_dir.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
            try:
                temporary.write_bytes(content)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        await asyncio.to_thread(restore)
    return path
