"""Verify a real photo through Nginx, upload processing and the configured model.

Run in the API container: python - /app/data/photo.jpg < deploy/verify_food_photo.py
Only the temporary account created by this script is removed afterward.
"""
import asyncio
import json
import secrets
import sys
from pathlib import Path

import httpx

from app.config import get_settings
from app.db import connect


async def cleanup(user_id):
    async with connect() as db:
        images = await (await db.execute('SELECT id FROM images WHERE user_id=?', (user_id,))).fetchall()
        for table in ('images', 'sessions', 'profiles'):
            await db.execute(f'DELETE FROM {table} WHERE user_id=?', (user_id,))
        await db.execute('DELETE FROM users WHERE id=?', (user_id,))
        await db.commit()
    for image in images:
        (get_settings().app_media_dir / (image['id'] + '.jpg')).unlink(missing_ok=True)
    print('Temporary photo check account and uploads removed', flush=True)


def main():
    photo = Path(sys.argv[1])
    user_id = None
    try:
        with httpx.Client(base_url='http://web', timeout=120) as client:
            response = client.post('/api/auth/register', json={
                'email': 'photo-check-' + secrets.token_hex(6) + '@example.invalid',
                'password': secrets.token_urlsafe(24),
            })
            response.raise_for_status()
            user_id = response.json()['user_id']
            uploaded = client.post('/api/images', files={'file': (
                photo.name, photo.read_bytes(), 'image/jpeg'
            )})
            uploaded.raise_for_status()
            image_id = uploaded.json()['id']
            print('Real photo upload:', uploaded.status_code, flush=True)
            for attempt in range(2):
                recognized = client.post('/api/meals/recognize', json={'image_id': image_id})
                recognized.raise_for_status()
                items = recognized.json()['items']
                assert len(items) >= 4, 'Expected several food candidates in the meal photo'
                assert all(x['name'] and 5 <= x['estimated_grams'] <= 3000 for x in items)
                print('Recognition attempt', attempt + 1, ':', recognized.status_code,
                      json.dumps(items, ensure_ascii=False), flush=True)
    finally:
        if user_id:
            asyncio.run(cleanup(user_id))


if __name__ == '__main__':
    main()
