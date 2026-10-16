"""Food provenance, validation and conservative matching for the shared catalog."""
import hashlib
import json
import math
import re
import unicodedata

from .db import connect


PREPARATIONS = {'生鲜', '煮熟', '蒸熟', '炒熟', '煎熟', '烤熟', '炸熟', '炖熟', '干制', '即食', '饮用', '烘焙'}


def normalize_name(value):
    value = unicodedata.normalize('NFKC', str(value)).lower()
    return re.sub(r'[\s\W_]+', '', value)


def validate_food(item, category):
    if not isinstance(item, dict):
        raise ValueError('food must be an object')
    if not isinstance(item.get('name'), str):
        raise ValueError('food name must be text')
    name = item['name'].strip()
    state = str(item.get('preparation') or '').strip()
    if not 1 <= len(name) <= 100 or state not in PREPARATIONS:
        raise ValueError('invalid food name or preparation')
    if item.get('basis_g') != 100:
        raise ValueError('nutrition must be per 100g edible portion')
    values = {}
    for key in ('kcal', 'protein', 'fat', 'carbs'):
        value = item.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f'invalid {key}')
        if not 0 <= value <= (930 if key == 'kcal' else 100):
            raise ValueError(f'{key} out of range')
        values[key] = round(float(value), 2)
    if values['protein'] + values['fat'] + values['carbs'] > 103:
        raise ValueError('macronutrients exceed 100g portion')
    macro_energy = 4 * values['protein'] + 9 * values['fat'] + 4 * values['carbs']
    # A coarse plausibility check only; passing does not establish accuracy.
    if abs(values['kcal'] - macro_energy) > max(25, 0.25 * max(values['kcal'], macro_energy)):
        raise ValueError('energy/macronutrients inconsistent')
    aliases = item.get('aliases', [])
    if aliases is None:
        aliases = []
    elif isinstance(aliases, str):
        aliases = re.split(r'[、,，;；]', aliases)
    if not isinstance(aliases, list) or any(not isinstance(x, str) for x in aliases):
        raise ValueError('invalid aliases')
    aliases = list(dict.fromkeys(x.strip() for x in aliases if 1 <= len(x.strip()) <= 60))[:8]
    return {'code': 'ai_' + hashlib.sha256(normalize_name(name).encode()).hexdigest()[:20],
            'name': name, **values, 'category': category, 'preparation': state,
            'basis_g': 100, 'aliases': aliases}


async def initialize_catalog():
    async with connect() as db:
        mysql = db.engine == 'mysql'
        code_type = 'VARCHAR(64) CHARACTER SET ascii' if mysql else 'TEXT'
        suffix = ' ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin' if mysql else ''
        await db.executescript(f'''
        CREATE TABLE IF NOT EXISTS food_metadata(
          food_code {code_type} PRIMARY KEY, category VARCHAR(64) NOT NULL,
          preparation VARCHAR(32) NOT NULL, aliases_json TEXT NOT NULL,
          source_type VARCHAR(32) NOT NULL, source_model VARCHAR(128) NOT NULL,
          batch_id VARCHAR(64) NOT NULL, basis_g INTEGER NOT NULL DEFAULT 100,
          verified INTEGER NOT NULL DEFAULT 0,
          created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ){suffix};
        CREATE TABLE IF NOT EXISTS food_import_batches(
          id {code_type} PRIMARY KEY, model VARCHAR(128) NOT NULL,
          status VARCHAR(32) NOT NULL, config_json TEXT NOT NULL,
          stats_json TEXT NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ){suffix};
        ''')
        await db.commit()


async def catalog_rows():
    async with connect() as db:
        rows = await (await db.execute('''SELECT f.*, m.category, m.preparation, m.aliases_json,
            m.source_type, m.source_model, m.batch_id, m.basis_g, m.verified
            FROM foods f LEFT JOIN food_metadata m ON m.food_code=f.code ORDER BY f.name''')).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        item['category'] = item['category'] or '原有食品'
        item['preparation'] = item['preparation'] or ''
        item['source_type'] = item['source_type'] or 'demo'
        item['source_model'] = item['source_model'] or ''
        item['batch_id'] = item['batch_id'] or ''
        item['basis_g'] = item['basis_g'] or 100
        item['verified'] = bool(item['verified'])
        item['aliases'] = json.loads(item.pop('aliases_json') or '[]')
        output.append(item)
    return output


def match_food(name, foods):
    """Match exact names/aliases, prefer a prepared form for a meal photograph.

    Do not match an arbitrary substring such as 鸡 to every chicken dish.
    Equal-ranked alternatives remain unselected for the user to resolve.
    """
    target = normalize_name(name)
    if not target:
        return None
    ranked = []
    explicit_raw = bool(re.search(r'生鲜|未煮|生肉|[（(]生[）)]', name))
    for food in foods:
        full = normalize_name(food['name'])
        base = normalize_name(re.sub(r'[（(].*?[）)]', '', food['name']))
        aliases = {normalize_name(x) for x in food.get('aliases', [])}
        prepared = food.get('preparation') in {'煮熟', '蒸熟', '炒熟', '煎熟', '烤熟', '炸熟', '炖熟', '即食', '饮用', '烘焙'}
        cooked_base = re.sub(r'^(?:水煮|白灼|清蒸|清炒|清炖|蒸|煮|烤|炒|煎|炸|炖)(?=.{2,}$)', '', base) if prepared else base
        rank = 4 if target == full else 3 if target in {base,cooked_base} else 2 if target in aliases else 0
        if rank == 4 and food.get('preparation') == '生鲜' and not explicit_raw:
            rank = 3
        if not rank:
            continue
        score = (rank, int(prepared and not explicit_raw))
        ranked.append((score, food['code']))
    if not ranked:
        return None
    best = max(x[0] for x in ranked)
    matches = {code for score, code in ranked if score == best}
    return next(iter(matches)) if len(matches) == 1 else None
