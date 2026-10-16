"""Run inside the API container against Nginx; remove only this check's data."""
import asyncio
import io
import json
import secrets
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from PIL import Image

from app.config import get_settings
from app.db import connect

STATE = Path('/app/data/.deployment-check.json')
BASE = 'http://web'


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print('PASS:', message, flush=True)


async def cleanup(state):
    async with connect() as db:
        for user_id in state['users']:
            meals = await (await db.execute('SELECT id FROM meals WHERE user_id=?', (user_id,))).fetchall()
            for meal in meals:
                await db.execute('DELETE FROM meal_items WHERE meal_id=?', (meal['id'],))
            for table in ('sessions', 'profiles', 'images', 'meals', 'chat_messages', 'nutrition_reports'):
                await db.execute(f'DELETE FROM {table} WHERE user_id=?', (user_id,))
            await db.execute('DELETE FROM users WHERE id=?', (user_id,))
        await db.commit()
    if state.get('image_id'):
        (get_settings().app_media_dir / (state['image_id'] + '.jpg')).unlink(missing_ok=True)
    STATE.unlink(missing_ok=True)
    print('PASS: deployment check accounts and records removed', flush=True)


def save(state):
    STATE.touch(mode=0o600, exist_ok=True)
    STATE.write_text(json.dumps(state), encoding='utf-8')


def prepare():
    state = {'users': []}
    with httpx.Client(base_url=BASE, timeout=180) as client:
        check(client.get('/').status_code == 200, 'H5 served by Nginx')
        check(client.get('/api/health').json() == {'status': 'ok', 'demo': False}, 'real mode API health')
        check(client.get('/api/profile').status_code == 401, 'authentication required')
        credentials = {'email': 'deployment-' + secrets.token_hex(6) + '@example.invalid', 'password': secrets.token_urlsafe(24)}
        registered = client.post('/api/auth/register', json=credentials)
        check(registered.status_code == 201, 'MySQL account creation')
        state['users'].append(registered.json()['user_id'])
        save(state)
        check(client.post('/api/auth/register', json=credentials).status_code == 409, 'duplicate account returns 409')
        check(client.post('/api/auth/logout').status_code == 200, 'logout')
        check(client.post('/api/auth/login', json=credentials).status_code == 200, 'login persisted in MySQL')
        profile = {'name': '部署验收🌱?100%', 'age': 30, 'height_cm': 170, 'weight_kg': 65, 'goal': 'balanced'}
        check(client.put('/api/profile', json=profile).status_code == 200, 'profile saved')
        check(client.get('/api/profile').json()['name'] == profile['name'], 'Chinese and emoji round trip')
        check(len(client.get('/api/foods').json()) == 10, 'food seed data')
        image = io.BytesIO()
        Image.new('RGB', (96, 96), 'white').save(image, format='PNG')
        uploaded = client.post('/api/images', files={'file': ('blank.png', image.getvalue(), 'image/png')})
        check(uploaded.status_code == 201, 'image upload')
        state['image_id'] = uploaded.json()['id']
        save(state)
        image_url = '/api/images/' + state['image_id']
        check(client.get(image_url).headers.get('content-type', '').startswith('image/jpeg'), 'authenticated Nginx image delivery')
        recognition = client.post('/api/meals/recognize', json={'image_id': state['image_id']})
        check(recognition.status_code == 200, 'real vision request: ' + str(recognition.status_code))
        check(isinstance(recognition.json()['items'], list), 'vision JSON parsed')
        meal = client.post('/api/meals', json={'meal_type': 'lunch', 'eaten_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(), 'image_id': state['image_id'], 'items': [{'food_code': 'rice', 'grams': 150}]})
        check(meal.status_code == 201, 'meal saved in MySQL')
        state['meal_id'] = meal.json()['id']
        check(client.get('/api/nutrition/summary?days=1').json()['totals']['kcal'] == 174, 'daily nutrition aggregation')
        chat = client.post('/api/chat/stream', json={'message': '请用一句话说明均衡早餐包含哪几类食物。', 'thread_id': 'deployment-check'})
        check(chat.status_code == 200 and 'event: done' in chat.text and 'event: error' not in chat.text, 'Qwen streaming consultation completed')
        history = client.get('/api/chat/history?thread_id=deployment-check').json()
        check(any(x['role'] == 'assistant' and x['content'].strip() for x in history), 'nonempty model answer persisted in MySQL')
        state['answer_length'] = len(history[-1]['content'])
        check(client.post('/api/reports/generate?days=7').status_code == 503, 'reports disabled')
        state['cookies'] = dict(client.cookies)
        save(state)
        other = client.post('/api/auth/register', json={'email': 'deployment-' + secrets.token_hex(6) + '@example.invalid', 'password': secrets.token_urlsafe(24)})
        check(other.status_code == 201, 'second check account')
        state['users'].append(other.json()['user_id'])
        save(state)
        check(client.get(image_url).status_code == 404, 'image isolated between accounts')
        check(client.get('/api/meals').json() == [], 'meal records isolated between accounts')
    print('PREPARE COMPLETE: restart API then run resume', flush=True)


def resume():
    state = json.loads(STATE.read_text(encoding='utf-8'))
    with httpx.Client(base_url=BASE, cookies=state['cookies'], timeout=15) as client:
        check(client.get('/api/auth/me').json()['id'] == state['users'][0], 'session survives API restart')
        check(any(x['id'] == state['meal_id'] for x in client.get('/api/meals').json()), 'meal survives API restart')
        check(client.get('/api/images/' + state['image_id']).status_code == 200, 'image survives API restart')
        check(any(x['role'] == 'assistant' and x['content'].strip() for x in client.get('/api/chat/history?thread_id=deployment-check').json()), 'chat survives API restart')
    asyncio.run(cleanup(state))
    print('DEPLOYMENT VERIFICATION COMPLETE', flush=True)


if __name__ == '__main__':
    phase = sys.argv[1] if len(sys.argv) > 1 else 'prepare'
    if phase == 'prepare':
        prepare()
    elif phase == 'resume':
        resume()
    elif phase == 'cleanup':
        asyncio.run(cleanup(json.loads(STATE.read_text(encoding='utf-8'))))
    else:
        raise SystemExit('Use prepare, resume or cleanup')
