"""Use one isolated temporary user; retain a per-revision model-check receipt."""
import argparse
import asyncio
from datetime import datetime, timezone
import io
import hashlib
import json
import secrets

import httpx
from PIL import Image

from app.config import get_settings
from app.db import connect


async def prior_model_check(revision):
    async with connect() as db:
        key = 'VARCHAR(128)' if db.engine == 'mysql' else 'TEXT'
        await db.execute(f'CREATE TABLE IF NOT EXISTS hosted_acceptance(revision {key} PRIMARY KEY, checked_at VARCHAR(40) NOT NULL)')
        await db.commit()
        return await (await db.execute('SELECT 1 FROM hosted_acceptance WHERE revision=?', (revision,))).fetchone() is not None


async def mark_model_check(revision):
    async with connect() as db:
        insert = 'INSERT IGNORE' if db.engine == 'mysql' else 'INSERT OR IGNORE'
        await db.execute(insert + ' INTO hosted_acceptance(revision,checked_at) VALUES(?,?)', (revision, datetime.now(timezone.utc).isoformat()))
        await db.commit()


async def cleanup(user_id, email):
    paths = []
    async with connect() as db:
        user = await (await db.execute('SELECT email FROM users WHERE id=?', (user_id,))).fetchone()
        if not user or user['email'] != email or not email.startswith('delivery-'):
            raise RuntimeError('Acceptance identity mismatch')
        images = await (await db.execute('SELECT id,path FROM images WHERE user_id=?', (user_id,))).fetchall()
        for image in images:
            if image['path'] == 'db:' + image['id']:
                await db.execute('DELETE FROM image_payloads WHERE image_id=?', (image['id'],))
            paths.append(get_settings().app_media_dir / (image['id'] + '.jpg'))
        await db.execute('DELETE FROM meal_item_estimates WHERE meal_item_id IN (SELECT i.id FROM meal_items i JOIN meals m ON m.id=i.meal_id WHERE m.user_id=?)', (user_id,))
        await db.execute('DELETE FROM meal_items WHERE meal_id IN (SELECT id FROM meals WHERE user_id=?)', (user_id,))
        for table in ('meal_recognitions', 'meals', 'chat_messages', 'nutrition_reports', 'sessions', 'profiles', 'images'):
            await db.execute(f'DELETE FROM {table} WHERE user_id=?', (user_id,))
        await db.execute('DELETE FROM users WHERE id=?', (user_id,))
        await db.commit()
    for path in paths:
        path.unlink(missing_ok=True)


def run(base_url, revision):
    settings = get_settings()
    model_config = {key: getattr(settings, key) for key in ('demo_mode', 'food_recognition_provider', 'vllm_chat_completions_url', 'vllm_model', 'vllm_api_key', 'vllm_vision_url', 'vllm_vision_model', 'vllm_vision_api_key')}
    receipt_key = revision + ':' + hashlib.sha256(json.dumps(model_config, sort_keys=True).encode()).hexdigest()
    already_checked = asyncio.run(prior_model_check(receipt_key))
    checks = []
    user_id = None
    email = 'delivery-' + secrets.token_hex(16) + '@example.invalid'
    try:
        with httpx.Client(base_url=base_url, timeout=110) as client:
            page = client.get('/')
            assert page.status_code == 200 and '<div id="app">' in page.text
            assert client.get('/api/health').json()['status'] == 'ok'
            assert client.get('/api/version').json()['revision'] == revision
            checks.extend(['frontend', 'health', 'revision'])
            account = client.post('/api/auth/register', json={'email': email, 'password': secrets.token_urlsafe(24)})
            account.raise_for_status()
            user_id = account.json()['user_id']
            # Only this loopback test copies its own Secure cookie to plain HTTP.
            token = account.cookies.get('nutrition_session')
            client.cookies.clear()
            client.cookies.set('nutrition_session', token)
            assert client.get('/api/auth/me').json()['id'] == user_id
            checks.append('authentication')
            foods = client.get('/api/foods').json()
            food = next((row for row in foods if row['code'] == 'rice'), foods[0])
            meal = client.post('/api/meals', json={'meal_type': 'lunch', 'eaten_at': datetime.now(timezone.utc).isoformat(), 'items': [{'food_code': food['code'], 'grams': 100}]})
            assert meal.status_code == 201
            assert abs(client.get('/api/nutrition/summary?days=1').json()['totals']['kcal'] - food['kcal']) < 0.02
            checks.extend(['meal-save', 'nutrition-summary'])
            image = io.BytesIO()
            Image.new('RGB', (40, 40), 'white').save(image, format='PNG')
            upload = client.post('/api/images', files={'file': ('acceptance.png', image.getvalue(), 'image/png')})
            assert upload.status_code == 201
            image_id = upload.json()['id']
            photo = client.get('/api/images/' + image_id)
            assert photo.status_code == 200
            if settings.app_image_storage == 'database':
                (settings.app_media_dir / (image_id + '.jpg')).unlink(missing_ok=True)
                assert client.get('/api/images/' + image_id).content == photo.content
                checks.append('photo-survives-cache-loss')
            if not already_checked:
                response = client.post('/api/chat/stream', json={'message': '用一句话说明均衡早餐包含哪些食物。', 'thread_id': 'delivery-check'})
                assert response.status_code == 200 and 'event: done' in response.text and 'event: delta' in response.text and 'event: error' not in response.text
                response = client.post('/api/meals/recognize', json={'image_id': image_id})
                assert response.status_code == 200 and isinstance(response.json()['items'], list)
                asyncio.run(mark_model_check(receipt_key))
                checks.append('model-chat-and-vision')
            client.cookies.clear()
            assert client.get('/api/images/' + image_id).status_code == 401
            checks.append('private-photos')
    finally:
        if user_id:
            asyncio.run(cleanup(user_id, email))
    print(json.dumps({'status': 'passed', 'revision': revision, 'checks': checks}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    run(args.base_url, args.revision)
