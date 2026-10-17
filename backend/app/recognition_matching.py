"""Resolve retrieved food codes against the live catalog without trusting AI nutrition.

The caller must obtain retrieval codes from the actual knowledge-search step. This
module validates their meaning against current catalog rows; a model's assertion
of a code (or snapshot/hash) is not proof that knowledge retrieval happened.
"""
from copy import deepcopy
import re

from .food_catalog import normalize_name


_COOKED = {'煮熟', '蒸熟', '炒熟', '煎熟', '烤熟', '炸熟', '炖熟', '烘焙'}
_PREPARATIONS = _COOKED | {'生鲜', '干制', '即食', '饮用'}
_PREPARATION_ALIASES = {
    '生': '生鲜', '生食': '生鲜', '未煮': '生鲜', '生的': '生鲜',
    '水煮': '煮熟', '白灼': '煮熟', '煮': '煮熟',
    '清蒸': '蒸熟', '蒸': '蒸熟', '清炒': '炒熟', '炒': '炒熟',
    '煎': '煎熟', '烤': '烤熟', '炸': '炸熟', '油炸': '炸熟',
    '炖': '炖熟', '清炖': '炖熟', '干': '干制',
    '蒸制': '蒸熟', '煮制': '煮熟', '炒制': '炒熟', '煎制': '煎熟',
    '烤制': '烤熟', '炸制': '炸熟', '炖制': '炖熟',
    '熟': '熟制', '熟食': '熟制', '熟的': '熟制',
}
_PREFIXES = (
    ('水煮', '煮熟'), ('白灼', '煮熟'), ('清蒸', '蒸熟'),
    ('清炒', '炒熟'), ('清炖', '炖熟'), ('油炸', '炸熟'),
    ('蒸', '蒸熟'), ('煮', '煮熟'), ('炒', '炒熟'),
    ('煎', '煎熟'), ('烤', '烤熟'), ('炸', '炸熟'), ('炖', '炖熟'),
)
_SHAPE_FOODS = {'土豆', '马铃薯', '玉米', '胡萝卜', '白萝卜', '莲藕', '黄瓜',
                '西葫芦', '山药', '紫薯', '红薯', '牛肉', '猪肉', '羊肉', '鸡肉', '鸡胸肉', '鸭肉'}
_PUBLIC_FIELDS = (
    'code', 'name', 'kcal', 'protein', 'fat', 'carbs', 'category',
    'preparation', 'basis_g', 'aliases', 'source_type', 'source_model',
    'batch_id', 'verified',
)


def _preparation(value):
    if not isinstance(value, str):
        return ''
    value = value.strip()
    return _PREPARATION_ALIASES.get(value, value)


def _name_preparation(name):
    if re.search(r'生鲜|未煮|生肉|[（(]生[）)]|生鱼片|刺身', name):
        return '生鲜'
    annotated = _annotated_preparation(name)
    if annotated:
        return annotated
    for prefix, state in _PREFIXES:
        if name.startswith(prefix) and len(name) > len(prefix):
            return state
    return ''


def _annotation_parts(value):
    return [part.strip() for part in re.split(r'[、,，;；/]', value) if part.strip()]


def _annotated_preparation(name):
    states = {
        _preparation(part)
        for value in re.findall(r'[（(]([^()（）]+)[）)]', name)
        for part in _annotation_parts(value)
        if _preparation(part) in _PREPARATIONS | {'熟制'}
    }
    return next(iter(states)) if len(states) == 1 else ''


def _effective_preparation(food):
    # Missing metadata is not a wildcard. Only an explicit canonical-name
    # annotation can establish the preparation of an old reference record.
    stored = _preparation(food.get('preparation'))
    return (stored, False) if stored else (_annotated_preparation(food['name']), True)


def _compatible(expected, actual):
    if actual == '熟制':
        return expected in {'', '熟制', '蒸熟', '煮熟'}
    return not expected or expected == actual or expected == '熟制' and actual in _COOKED


def _base_name(name, preparation):
    # Only remove preparation annotations, never qualifiers such as 无糖/带皮.
    def remove_state(match):
        parts = _annotation_parts(match.group(1))
        kept = [part for part in parts if _preparation(part) not in _PREPARATIONS | {'熟制'}]
        if len(kept) == len(parts):
            return match.group(0)
        return match.group(0)[0] + '，'.join(kept) + match.group(0)[-1] if kept else ''
    name = re.sub(r'[（(]([^()（）]+)[）)]', remove_state, name)
    for prefix, state in _PREFIXES:
        if preparation == state and name.startswith(prefix) and len(name) > len(prefix) + 1:
            name = name[len(prefix):]
            break
    name = normalize_name(name)
    # Cutting shape does not change a plain ingredient's identity. Only this
    # closed ingredient list qualifies; never strip recipe words or qualifiers.
    if len(name) > 1 and name[-1] in '片丝丁块段粒条' and name[:-1] in _SHAPE_FOODS:
        name = name[:-1]
    return name


def _name_rank(name, food, expected):
    target = normalize_name(name)
    if target == normalize_name(food['name']):
        return 3
    if target in {normalize_name(alias) for alias in food.get('aliases', [])}:
        return 2
    # A known preparation permits 鸡胸肉（生）/水煮鸡胸肉 to share a base,
    # but does not make arbitrary substrings or condiment changes equivalent.
    actual, _ = _effective_preparation(food)
    if (expected or actual) and _base_name(name, expected) == _base_name(food['name'], actual):
        return 1
    return 0


def _match_score(name, food, expected):
    rank = _name_rank(name, food, expected)
    actual, _ = _effective_preparation(food)
    # At the same name/alias rank, an explicit cooking method is more specific
    # than an old generic cooked reference. An exact name still outranks aliases.
    specific = int(actual in _PREPARATIONS)
    return rank, specific


def _public_food(food):
    return {key: deepcopy(food[key]) for key in _PUBLIC_FIELDS if key in food}


def _retrieved_candidates(item, by_code):
    """Return live candidates and codes whose supplied identity became stale."""
    evidence = {}
    codes = item.get('retrieved_codes')
    has_codes = isinstance(codes, list)
    if has_codes:
        evidence.update((code, None) for code in codes if isinstance(code, str) and code)
    candidates = item.get('candidates')
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            code = candidate.get('food_code') or candidate.get('code')
            if isinstance(code, str) and code and (not has_codes or code in evidence):
                evidence[code] = candidate
    live, stale = {}, set()
    for code, candidate in evidence.items():
        food = by_code.get(code)
        if not food:
            continue
        if food.get('basis_g', 100) != 100 or candidate and (
            'name' in candidate and normalize_name(candidate['name']) != normalize_name(food['name'])
            or 'preparation' in candidate and _preparation(candidate['preparation']) != _preparation(food.get('preparation'))
        ):
            stale.add(code)
            continue
        live[code] = food
    return evidence, live, stale


def resolve_recognized_items(items: list[dict], catalog: list[dict]) -> list[dict]:
    """Keep visual names/weights and preselect only an unambiguous retrieved food.

    Inputs have already passed the recognition adapter's shape/weight checks.
    Candidate metadata is optional. No hash/snapshot verification is claimed here;
    only supplied candidate names/preparations and current database rows are checked.
    Explicit cooked-name annotations can qualify legacy reference records without
    changing their returned metadata. Nutrition/provenance come from the live DB.
    """
    by_code = {food['code']: food for food in catalog}
    output = []
    for item in items:
        result = {
            'name': item['name'], 'estimated_grams': item['estimated_grams'],
            'food_code': None, 'match_status': 'no_evidence',
            'matched_name': None, 'matched_food': None, 'candidates': [],
        }
        if 'preparation' in item:
            result['preparation'] = item['preparation']
        # Keep actual document provenance available to the UI/diagnostics. The
        # adapter has already bounded and whitelisted these fields.
        for key in ('retrieval_evidence', 'snapshot_id'):
            if key in item:
                result[key] = deepcopy(item[key])
        evidence, candidates, stale = _retrieved_candidates(item, by_code)
        result['candidates'] = [_public_food(food) for food in candidates.values()]
        selected = item.get('food_code')
        state = _preparation(item.get('preparation'))
        inferred_state = _name_preparation(item['name'])
        if not evidence or selected and selected not in evidence:
            status = 'no_evidence'
        elif selected and selected not in by_code:
            status = 'not_found'
        elif selected in stale or not candidates and stale:
            status = 'stale_candidate'
        elif not candidates:
            status = 'not_found'
        elif state and inferred_state and not (_compatible(state, inferred_state) or _compatible(inferred_state, state)):
            status = 'preparation_conflict'
        else:
            expected = inferred_state if state == '熟制' and inferred_state else state or inferred_state
            named = [(code, _match_score(item['name'], food, expected)) for code, food in candidates.items()]
            named = [(code, score) for code, score in named if score[0]]
            compatible = [(code, score) for code, score in named if _compatible(expected, _effective_preparation(candidates[code])[0])]
            if not named:
                status = 'name_mismatch'
            elif not compatible:
                status = 'preparation_conflict'
            else:
                best_rank = max(rank for _, rank in compatible)
                best = [code for code, rank in compatible if rank == best_rank]
                if len(best) != 1:
                    status = 'ambiguous'
                elif any(
                    food['code'] != best[0]
                    and _compatible(expected, _effective_preparation(food)[0])
                    and _match_score(item['name'], food, expected) >= best_rank
                    for food in catalog
                ):
                    # Retrieval top-K can omit another exact-name/alias match.
                    # The full catalog may veto uncertainty, never supply a code.
                    status = 'ambiguous'
                elif selected and selected != best[0]:
                    status = 'preparation_conflict' if any(code == selected for code, _ in named) and not any(code == selected for code, _ in compatible) else 'name_mismatch'
                else:
                    food = candidates[best[0]]
                    result.update(food_code=food['code'], matched_name=food['name'], matched_food=_public_food(food))
                    actual, inferred = _effective_preparation(food)
                    if inferred and actual == '熟制':
                        result['match_note'] = 'legacy_cooked_reference'
                    status = 'matched'
        result['match_status'] = status
        output.append(result)
    return output
