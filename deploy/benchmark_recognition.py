"""Bounded real-image benchmark, executable only inside an isolated test API.

Run with PYTHONPATH=/app in a candidate API container. Images, per-request
results and account cleanup receipts belong outside Git. Fixture variations
exercise uncached visual inputs; they are NOT independent accuracy examples.
"""
import argparse
import asyncio
import hashlib
import io
import json
import math
from pathlib import Path
import secrets
import time
import uuid

import httpx
from PIL import Image, ImageEnhance


def summarize(records):
    if not records:
        raise ValueError('No completed requests')
    times = sorted(row['seconds'] for row in records)
    size = len(times)
    return {'requests': size, 'success': sum(row.get('status') == 200 for row in records),
            'p50': times[math.ceil(size * .50) - 1], 'p95': times[math.ceil(size * .95) - 1],
            'max': times[-1], 'under_20_seconds': sum(row.get('status') == 200 and row['seconds'] <= 20 for row in records)}


def private_json(path, value):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Report path must not be a symlink')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as handle:
        path.chmod(0o600)
        json.dump(value, handle, ensure_ascii=False, indent=2)


def fixture(path, index, vary):
    raw = Path(path).read_bytes()
    if not vary:
        return raw
    # Slight deterministic exposure changes prevent identical image encoder
    # cache hits while preserving the photographed meal and image dimensions.
    with Image.open(io.BytesIO(raw)) as original:
        picture = ImageEnhance.Brightness(original.convert('RGB')).enhance(.90 + index * .002)
        output = io.BytesIO()
        picture.save(output, format='JPEG', quality=90)
        return output.getvalue()


async def guarded_database():
    from app.config import get_settings
    from app.db import connect
    settings = get_settings()
    if settings.app_db_engine != 'mysql' or not settings.mysql_database.startswith('test_'):
        raise ValueError('Benchmarks require an isolated test_ MySQL database')
    async with connect() as database:
        current = await (await database.execute('SELECT DATABASE() AS name')).fetchone()
        if current['name'] != settings.mysql_database:
            raise ValueError('Actual database differs from test configuration')
    return settings


async def cleanup(user_id, email):
    from app.db import connect
    settings = await guarded_database()
    async with connect() as database:
        row = await (await database.execute('SELECT email FROM users WHERE id=?', (user_id,))).fetchone()
        if not row or row['email'] != email or not email.startswith('bench-'):
            raise ValueError('Cleanup identity mismatch')
        images = await (await database.execute('SELECT path FROM images WHERE user_id=?', (user_id,))).fetchall()
        await database.execute('DELETE FROM meal_item_estimates WHERE meal_item_id IN (SELECT i.id FROM meal_items i JOIN meals m ON m.id=i.meal_id WHERE m.user_id=?)', (user_id,))
        await database.execute('DELETE FROM meal_recognitions WHERE user_id=?', (user_id,))
        await database.execute('DELETE FROM meal_items WHERE meal_id IN (SELECT id FROM meals WHERE user_id=?)', (user_id,))
        for table in ('meals', 'chat_messages', 'nutrition_reports', 'sessions', 'profiles', 'images'):
            await database.execute(f'DELETE FROM {table} WHERE user_id=?', (user_id,))
        await database.execute('DELETE FROM users WHERE id=?', (user_id,))
        await database.commit()
    for row in images:
        path = Path(row['path']).resolve()
        if path.parent != settings.app_media_dir.resolve():
            raise ValueError('Refusing cleanup outside test media')
        path.unlink(missing_ok=True)


async def benchmark(args):
    settings = await guarded_database()
    # Always reach this candidate's own Nginx, never a supplied production URL.
    origin = 'http://web'
    clients, users = [], []
    result = {'label': args.label, 'database': settings.mysql_database,
              'revision': settings.app_revision, 'concurrency': args.concurrency, 'rounds': args.rounds,
              'scene_count': len(args.image), 'unique_exposure_variants': args.vary_images,
              'application_result_cache': False, 'includes_upload': True, 'requests': []}
    ledger = Path(str(args.report) + '.cleanup.json')
    try:
        for unused in range(args.concurrency):
            client = httpx.AsyncClient(base_url=origin, timeout=240)
            clients.append(client)
            email = f'bench-{secrets.token_hex(16)}@example.invalid'
            response = await client.post('/api/auth/register', json={'email': email, 'password': secrets.token_urlsafe(24)})
            response.raise_for_status()
            user_id = str(uuid.UUID(response.json()['user_id']))
            users.append({'id': user_id, 'email': email})
            private_json(ledger, users)
        for wave in range(args.rounds):
            inputs = [fixture(args.image[(wave * args.concurrency + i) % len(args.image)],
                              args.variant_offset + wave * args.concurrency + i, args.vary_images) for i in range(args.concurrency)]
            async def one(index, client):
                started = time.perf_counter()
                record = {'wave': wave, 'client': index, 'scene': (wave * args.concurrency + index) % len(args.image),
                          'input_sha256': hashlib.sha256(inputs[index]).hexdigest()}
                try:
                    upload = await client.post('/api/images', files={'file': ('meal.jpg', inputs[index], 'image/jpeg')})
                    upload.raise_for_status()
                    response = await client.post('/api/meals/recognize', json={'image_id': upload.json()['id']})
                    record['status'] = response.status_code
                    if response.status_code == 200:
                        value = response.json()
                        record.update(source=value['source'], coalesced=value.get('coalesced',False), server_elapsed_ms=value.get('elapsed_ms'),timings_ms=value.get('timings_ms'),
                                      items=[{key: item.get(key) for key in ('name', 'food_code', 'preparation', 'match_status')}
                                             for item in value['items']])
                    else:
                        record['error'] = 'http_' + str(response.status_code)
                except Exception as exc:
                    record['error'] = type(exc).__name__
                record['seconds'] = round(time.perf_counter() - started, 3)
                return record
            completed = await asyncio.gather(*(one(index, client) for index, client in enumerate(clients)))
            result['requests'].extend(completed)
            private_json(args.report, result)
            print(json.dumps({'wave': wave, **summarize(completed)}), flush=True)
    finally:
        for client in clients:
            await client.aclose()
        errors = []
        for user in users:
            try:
                await cleanup(user['id'], user['email'])
            except Exception as exc:
                errors.append({'id': user['id'], 'error': type(exc).__name__})
        result['cleanup_errors'] = errors
        if not errors:
            private_json(ledger, [])
        private_json(args.report, result)
        if errors:
            raise RuntimeError('Test cleanup incomplete; preserve private cleanup ledger')
    result['summary'] = summarize(result['requests'])
    result['target_passed'] = (result['summary']['success'] == len(result['requests']) and result['summary']['p95'] <= 20)
    private_json(args.report, result)
    print(json.dumps({'label': args.label, 'target_passed': result['target_passed'], **result['summary']}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    parser.add_argument('--concurrency', type=int, choices=range(1, 11), required=True)
    parser.add_argument('--rounds', type=int, choices=range(1, 11), default=5)
    parser.add_argument('--image', action='append', type=Path, required=True)
    parser.add_argument('--vary-images', action='store_true')
    parser.add_argument('--variant-offset', type=int, choices=range(0, 101), default=0)
    parser.add_argument('--report', type=Path, required=True)
    asyncio.run(benchmark(parser.parse_args()))


if __name__ == '__main__':
    main()
