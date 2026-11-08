import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app import main
from app.db import connect
from app.meal_estimates import nutrition_estimate
from test_bisheng_api_integration import recognition_api


ESTIMATE = {'basis_g': 100, 'kcal': 120, 'protein': 4, 'fat': 4, 'carbs': 17}


def recognize(fixture, monkeypatch, *, matched=False, nutrition=True):
    item = {'name': fixture.food['name'] if matched else '家常汤面', 'preparation': '煮熟',
            'estimated_grams': 450, 'food_code': fixture.food['code'] if matched else None,
            'retrieved_codes': [fixture.food['code']] if matched else []}
    if nutrition:
        item.update(nutrition=ESTIMATE, source_model='bisheng:model:44', source_type='ai_estimate', verified=False)
    async def workflow(*args):
        return [item]
    monkeypatch.setattr(main, 'recognize_workflow_image', workflow)
    photo = fixture.upload()
    result = fixture.client.post('/api/meals/recognize', json={'image_id': photo})
    assert result.status_code == 200, result.text
    return photo, result.json()


def payload(photo, result, code=None, grams=450):
    return {'meal_type': 'lunch', 'eaten_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
            'image_id': photo, 'recognition_id': result['recognition_id'],
            'items': [{'food_code': code, 'grams': grams, 'nutrition_source': 'model', 'recognition_index': 0}]}


@pytest.mark.parametrize('matched', [False, True])
def test_model_estimates_save_with_or_without_catalog_and_scale_weight(recognition_api, monkeypatch, matched):
    f = recognition_api
    photo, result = recognize(f, monkeypatch, matched=matched)
    assert result['items'][0]['nutrition'] == ESTIMATE
    before = f.client.get('/api/foods').json()
    body = payload(photo, result, f.food['code'] if matched else None, grams=225)
    # Posted nutrient claims cannot replace the server's model receipt.
    body['items'][0].update(kcal=99999, verified=True, source_model='forged')
    saved = f.client.post('/api/meals', json=body)
    assert saved.status_code == 201, saved.text
    records = f.client.get('/api/meals').json()
    item = next(m for m in records if m['id'] == saved.json()['id'])['items'][0]
    assert item['name'] == result['items'][0]['name']
    assert item['grams'] == 225 and item['kcal'] == 270
    assert item['protein'] == 9 and item['fat'] == 9 and item['carbs'] == 38.25
    assert item['food_code'] == (f.food['code'] if matched else None)
    assert item['source_type'] == 'ai_estimate' and item['verified'] is False
    assert item['source_model'] == 'bisheng:model:44' and item['basis_g'] == 100
    assert item['nutrition'] == ESTIMATE
    assert f.client.get('/api/nutrition/summary?days=1').json()['totals']['kcal'] == 270
    assert f.client.get('/api/foods').json() == before


def test_explicit_catalog_selection_uses_catalog_nutrients(recognition_api, monkeypatch):
    f = recognition_api
    photo, result = recognize(f, monkeypatch)
    body = payload(photo, result, f.food['code'], grams=100)
    body['items'][0]['nutrition_source'] = 'catalog'
    assert f.client.post('/api/meals', json=body).status_code == 201
    item = f.client.get('/api/meals').json()[0]['items'][0]
    assert item['kcal'] == f.food['kcal']
    assert item['name'] == f.food['name']


def test_receipt_is_bound_to_user_photo_and_item(recognition_api, monkeypatch):
    f = recognition_api
    photo, result = recognize(f, monkeypatch)
    body = payload(photo, result)
    for field, value in [('recognition_id', None), ('recognition_id', 'unknown'), ('image_id', f.upload())]:
        bad = {**body, field: value}
        assert f.client.post('/api/meals', json=bad).status_code == 422
    body['items'][0]['recognition_index'] = 7
    assert f.client.post('/api/meals', json=body).status_code == 422
    body = payload(photo, result)
    f.register()
    assert f.client.post('/api/meals', json=body).status_code in (404, 422)
    assert f.client.get('/api/meals').json() == []


def test_no_estimate_never_silently_saves_zero(recognition_api, monkeypatch):
    photo, result = recognize(recognition_api, monkeypatch, nutrition=False)
    assert recognition_api.client.post('/api/meals', json=payload(photo, result)).status_code == 422


@pytest.mark.parametrize('changes', [{'basis_g': 1}, {'basis_g': True}, {'kcal': -1}, {'kcal': 931},
                                     {'protein': True}, {'fat': float('nan')}, {'carbs': float('inf')},
                                     {'protein': 100, 'fat': 10}])
def test_invalid_model_nutrition_is_rejected(changes):
    with pytest.raises(ValueError):
        nutrition_estimate({**ESTIMATE, **changes})
