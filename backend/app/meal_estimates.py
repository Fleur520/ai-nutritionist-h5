"""Private recognition receipts and per-meal model estimates, never catalog rows."""
import json
import math
import uuid

from fastapi import HTTPException

from .db import connect

NUTRIENTS = ('kcal', 'protein', 'fat', 'carbs')


def nutrition_estimate(value):
    if not isinstance(value, dict) or type(value.get('basis_g')) not in (int, float) or value['basis_g'] != 100:
        raise ValueError('nutrition must use a 100g basis')
    result = {'basis_g': 100}
    for key in NUTRIENTS:
        number = value.get(key)
        if type(number) not in (int, float) or not math.isfinite(number) or not 0 <= number <= (930 if key == 'kcal' else 100):
            raise ValueError('invalid estimated ' + key)
        result[key] = round(number, 2)
    if sum(result[key] for key in NUTRIENTS[1:]) > 103:
        raise ValueError('estimated macronutrients exceed 100g')
    return result


async def initialize_estimates():
    # Additive tables leave every existing meal and food unchanged and permit
    # the previous release to continue reading stored nutrient totals.
    async with connect() as db:
        identity = 'CHAR(36) CHARACTER SET ascii' if db.engine == 'mysql' else 'TEXT'
        document = 'LONGTEXT' if db.engine == 'mysql' else 'TEXT'
        suffix = ' ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin' if db.engine == 'mysql' else ''
        await db.executescript(f'''
        CREATE TABLE IF NOT EXISTS meal_recognitions(
          id {identity} PRIMARY KEY, user_id {identity} NOT NULL,
          image_id {identity} NOT NULL, items_json {document} NOT NULL,
          provenance_json TEXT NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ){suffix};
        CREATE TABLE IF NOT EXISTS meal_item_estimates(
          meal_item_id {identity} PRIMARY KEY, name VARCHAR(100) NOT NULL,
          preparation VARCHAR(32) NOT NULL, source_type VARCHAR(32) NOT NULL,
          source_model VARCHAR(128) NOT NULL, basis_g INTEGER NOT NULL DEFAULT 100,
          verified INTEGER NOT NULL DEFAULT 0, nutrition_json TEXT NOT NULL,
          provenance_json TEXT NOT NULL
        ){suffix};
        ''')
        await db.commit()


async def save_recognition(user, image_id, items, provenance):
    receipt = str(uuid.uuid4())
    fields = ('name', 'estimated_grams', 'preparation', 'nutrition', 'source_model', 'food_code', 'snapshot_id')
    snapshot = [{key: item[key] for key in fields if key in item} for item in items]
    async with connect() as db:
        await db.execute('INSERT INTO meal_recognitions(id,user_id,image_id,items_json,provenance_json) VALUES(?,?,?,?,?)',
                         (receipt, user, image_id, json.dumps(snapshot, ensure_ascii=False), json.dumps(provenance)))
        await db.commit()
    return receipt


async def recognition_for_meal(db, body, user):
    if not any(item.nutrition_source == 'model' for item in body.items):
        return None
    if not body.recognition_id:
        raise HTTPException(422, '缺少模型识别记录，请重新识别照片')
    receipt = await (await db.execute('SELECT * FROM meal_recognitions WHERE id=? AND user_id=?',
                                     (body.recognition_id, user))).fetchone()
    if not receipt or receipt['image_id'] != body.image_id:
        raise HTTPException(422, '模型识别记录与本餐照片不一致，请重新识别')
    return {'items': json.loads(receipt['items_json']), 'provenance': json.loads(receipt['provenance_json'])}


def model_item(item, receipt):
    index = item.recognition_index
    if receipt is None or index is None or index >= len(receipt['items']):
        raise HTTPException(422, '缺少该食物的模型估算，请重新识别或选择食品库数据')
    original = receipt['items'][index]
    try:
        estimate = nutrition_estimate(original.get('nutrition'))
    except ValueError as exc:
        raise HTTPException(422, '该食物没有有效模型营养估算，请重新识别或选择食品库数据') from exc
    return original, estimate
