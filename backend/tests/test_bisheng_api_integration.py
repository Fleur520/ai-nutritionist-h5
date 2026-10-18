"""Exercise the image-recognition API with real, isolated catalog/image storage.

Only the external recognition call is replaced. Authentication, private uploads,
database reconciliation, meal persistence and nutrition calculation remain real.
"""
import asyncio
import io
import os
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from app import db as database
from app import main
from app.config import Settings


@pytest.fixture
def recognition_api(tmp_path, monkeypatch):
    engine = os.environ.get('TEST_DB_ENGINE', 'sqlite')
    mysql_database = os.environ.get('TEST_MYSQL_DATABASE', '')
    if engine == 'mysql' and not mysql_database.startswith('test_'):
        raise RuntimeError('MySQL tests require TEST_MYSQL_DATABASE starting with test_')
    settings = Settings(
        _env_file=None, app_db_engine=engine,
        mysql_database=mysql_database if engine == 'mysql' else 'test_unused',
        app_db_path=tmp_path / 'recognition.sqlite3', app_media_dir=tmp_path / 'media',
        demo_mode=False, app_cookie_secure=False, app_nginx_accel=False,
        food_recognition_provider='bisheng',
    )
    monkeypatch.setattr(database, 'get_settings', lambda: settings)
    monkeypatch.setattr(main, 'settings', settings)
    monkeypatch.setattr(main, 'AI_SEM', asyncio.Semaphore(1))
    unique = uuid.uuid4().hex[:12]
    food = {
        'code': 'test_bisheng_' + unique, 'name': '蒸紫薯（接口测试' + unique + '）',
        'kcal': 86.0, 'protein': 1.6, 'fat': 0.2, 'carbs': 19.5,
        'preparation': '蒸熟', 'category': '薯类', 'aliases': [],
        'source_type': 'ai_estimate', 'source_model': 'test-model',
        'batch_id': 'test-batch-' + unique, 'basis_g': 100, 'verified': False,
    }
    users = []

    async def seed_food():
        async with database.connect() as db:
            await db.execute('INSERT INTO foods(code,name,kcal,protein,fat,carbs) VALUES(?,?,?,?,?,?)',
                             tuple(food[key] for key in ('code', 'name', 'kcal', 'protein', 'fat', 'carbs')))
            await db.execute('''INSERT INTO food_metadata
                (food_code,category,preparation,aliases_json,source_type,source_model,batch_id,basis_g,verified)
                VALUES(?,?,?,?,?,?,?,?,?)''',
                (food['code'], food['category'], food['preparation'], '[]', food['source_type'],
                 food['source_model'], food['batch_id'], 100, 0))
            await db.commit()

    async def cleanup():
        async with database.connect() as db:
            for user in users:
                await db.execute('DELETE FROM meal_items WHERE meal_id IN (SELECT id FROM meals WHERE user_id=?)', (user,))
                for table in ('meals', 'images', 'sessions', 'profiles'):
                    await db.execute(f'DELETE FROM {table} WHERE user_id=?', (user,))
                await db.execute('DELETE FROM users WHERE id=?', (user,))
            await db.execute('DELETE FROM food_metadata WHERE food_code=?', (food['code'],))
            await db.execute('DELETE FROM foods WHERE code=?', (food['code'],))
            await db.commit()

    with TestClient(main.app) as client:
        asyncio.run(seed_food())

        def register():
            response = client.post('/api/auth/register', json={
                'email': 'recognition-' + uuid.uuid4().hex + '@example.com',
                'password': 'isolated_test_password_123',
            })
            assert response.status_code == 201, response.text
            users.append(response.json()['user_id'])
            return response.json()['user_id']

        def upload():
            image = io.BytesIO()
            Image.new('RGB', (40, 40), 'purple').save(image, format='PNG')
            response = client.post('/api/images', files={'file': ('synthetic-meal.png', image.getvalue(), 'image/png')})
            assert response.status_code == 201, response.text
            return response.json()['id']

        register()
        try:
            yield SimpleNamespace(client=client, food=food, register=register, upload=upload,
                                  settings=settings)
        finally:
            asyncio.run(cleanup())


def test_image_encoding_can_overlap_without_blocking_other_uploads(recognition_api, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    barrier=threading.Barrier(2,timeout=5)
    original=main.encode_uploaded_image
    threads=set()
    lock=threading.Lock()
    def encode(raw,path):
        with lock:threads.add(threading.get_ident())
        barrier.wait()
        original(raw,path)
    monkeypatch.setattr(main,'encode_uploaded_image',encode)
    monkeypatch.setattr(main,'IMAGE_SEM',asyncio.Semaphore(2))
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids=list(pool.map(lambda _:recognition_api.upload(),range(2)))
    assert len(set(ids))==2 and len(threads)==2


def workflow_item(food):
    return {
        'name': food['name'], 'preparation': '蒸熟', 'estimated_grams': 150,
        'food_code': food['code'], 'retrieved_codes': [food['code']],
        # Deliberately forged nutrition/provenance must never reach API output.
        'kcal': 9999, 'verified': True, 'source_type': 'verified_reference',
        'candidates': [{**food, 'kcal': 9999, 'protein': 99,
                        'verified': True, 'source_type': 'verified_reference'}],
    }


def reject_direct_call(monkeypatch):
    async def direct(*args, **kwargs):
        pytest.fail('BiSheng provider must not invoke the direct recognition provider')
    monkeypatch.setattr(main, 'recognize_image', direct)


def test_workflow_refills_live_database_food_and_saved_meal_nutrition(recognition_api, monkeypatch):
    api = recognition_api
    image_id = api.upload()
    calls = []

    async def workflow(path, mime, timings=None):
        calls.append((path, mime))
        assert path.parent == api.settings.app_media_dir
        assert path.is_file() and path.suffix == '.jpg'
        return [workflow_item(api.food)]

    monkeypatch.setattr(main, 'recognize_workflow_image', workflow)
    reject_direct_call(monkeypatch)
    response = api.client.post('/api/meals/recognize', json={'image_id': image_id})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['source'] == 'bisheng'
    assert set(body['timings_ms']) == {'admission', 'workflow', 'catalog', 'matching'}
    assert all(isinstance(value, int) and value >= 0 for value in body['timings_ms'].values())
    assert len(calls) == 1 and calls[0][1] == 'image/jpeg'
    item = body['items'][0]
    assert item['food_code'] == api.food['code']
    assert item['match_status'] == 'matched'
    assert item['estimated_grams'] == 150
    assert item['matched_name'] == api.food['name']
    assert item['matched_food'] == api.food
    assert item['candidates'] == [api.food]
    assert 'kcal' not in item and 'verified' not in item
    assert '未经实验核验' in body['notice']
    catalog_food = next(food for food in api.client.get('/api/foods').json()
                        if food['code'] == item['food_code'])
    assert item['matched_food'] == catalog_food

    meal = api.client.post('/api/meals', json={
        'meal_type': 'lunch', 'eaten_at': '2026-10-17T12:00:00+08:00', 'image_id': image_id,
        'items': [{'food_code': item['food_code'], 'grams': item['estimated_grams']}],
    })
    assert meal.status_code == 201, meal.text
    meals = api.client.get('/api/meals', params={'day': '2026-10-17'}).json()
    saved = next(row for row in meals if row['id'] == meal.json()['id'])['items'][0]
    assert saved['food_code'] == api.food['code']
    for nutrient in ('kcal', 'protein', 'fat', 'carbs'):
        assert saved[nutrient] == round(api.food[nutrient] * 1.5, 2)


def test_workflow_cannot_select_database_code_without_retrieval_evidence(recognition_api, monkeypatch):
    api = recognition_api
    image_id = api.upload()

    async def workflow(*args):
        item = workflow_item(api.food)
        item['retrieved_codes'] = []
        return [item]

    monkeypatch.setattr(main, 'recognize_workflow_image', workflow)
    reject_direct_call(monkeypatch)
    response = api.client.post('/api/meals/recognize', json={'image_id': image_id})
    assert response.status_code == 200, response.text
    item = response.json()['items'][0]
    assert item['food_code'] is None
    assert item['matched_food'] is None
    assert item['match_status'] == 'no_evidence'
    assert item['candidates'] == []


@pytest.mark.parametrize('status', [502, 503])
def test_workflow_failure_is_returned_without_fallback_and_releases_capacity(recognition_api, monkeypatch, status):
    api = recognition_api
    image_id = api.upload()
    calls = []

    async def workflow(*args):
        calls.append(True)
        if len(calls) == 1:
            raise HTTPException(status, '餐食识别工作流暂时不可用')
        return [workflow_item(api.food)]

    monkeypatch.setattr(main, 'recognize_workflow_image', workflow)
    reject_direct_call(monkeypatch)
    failed = api.client.post('/api/meals/recognize', json={'image_id': image_id})
    assert failed.status_code == status
    assert failed.json() == {'detail': '餐食识别工作流暂时不可用'}
    retry = api.client.post('/api/meals/recognize', json={'image_id': image_id})
    assert retry.status_code == 200, retry.text
    assert retry.json()['source'] == 'bisheng'
    assert len(calls) == 2


def test_private_or_missing_image_never_reaches_workflow(recognition_api, monkeypatch):
    api = recognition_api
    image_id = api.upload()

    async def workflow(*args):
        pytest.fail('An inaccessible image must never be sent to BiSheng')

    monkeypatch.setattr(main, 'recognize_workflow_image', workflow)
    reject_direct_call(monkeypatch)
    api.register()  # A different signed-in user cannot access the first upload.
    assert api.client.get('/api/images/' + image_id).status_code == 404
    for candidate in (image_id, str(uuid.uuid4())):
        response = api.client.post('/api/meals/recognize', json={'image_id': candidate})
        assert response.status_code == 404
        assert response.json() == {'detail': '图片不存在'}
    api.client.cookies.clear()
    assert api.client.post('/api/meals/recognize', json={'image_id': image_id}).status_code == 401
