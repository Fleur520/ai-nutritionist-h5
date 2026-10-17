"""Deterministic knowledge-retrieval matching, using a small invented catalog."""
from copy import deepcopy

import pytest

from app.recognition_matching import resolve_recognized_items


@pytest.fixture
def catalog():
    def row(code, name, preparation, aliases, kcal):
        return {
            'code': code, 'name': name, 'preparation': preparation,
            'aliases': aliases, 'kcal': kcal, 'protein': 1.2, 'fat': .3,
            'carbs': 20, 'basis_g': 100, 'category': '测试食品',
            'source_type': 'ai_estimate', 'source_model': 'fixture-model',
            'batch_id': 'fixture-batch', 'verified': False,
        }
    return [
        row('rice', '白米饭', '煮熟', ['米饭'], 110),
        row('raw_rice', '大米（生）', '生鲜', ['生大米'], 340),
        row('steamed', '蒸紫薯', '蒸熟', ['紫薯'], 90),
        row('raw', '紫薯（生）', '生鲜', ['紫薯'], 85),
        row('baked', '烤紫薯', '烤熟', ['紫薯'], 100),
        row('apple', '苹果', '生鲜', ['红苹果'], 50),
        row('fresh_longan', '龙眼', '生鲜', ['桂圆'], 60),
        row('dried_longan', '龙眼干', '干制', ['桂圆'], 280),
        row('tofu', '家常豆腐', '炒熟', ['家常菜'], 100),
        row('spicy_tofu', '麻婆豆腐', '炒熟', ['家常豆腐'], 120),
    ]


def resolve(catalog, **changes):
    item = {'name': '米饭', 'estimated_grams': 123.5, 'retrieved_codes': ['rice']}
    item.update(changes)
    return resolve_recognized_items([item], catalog)[0]


def test_unique_alias_uses_live_values_and_keeps_visual_name_weight(catalog):
    result = resolve(catalog, kcal=999999, verified=True, source_type='official')
    assert result['food_code'] == 'rice'
    assert result['match_status'] == 'matched'
    assert result['name'] == '米饭' and result['estimated_grams'] == 123.5
    assert result['matched_name'] == '白米饭'
    assert result['matched_food'] == catalog[0]
    assert result['matched_food']['verified'] is False
    assert result['matched_food']['basis_g'] == 100
    assert 'kcal' not in result and 'verified' not in result


@pytest.mark.parametrize('changes,status', [
    ({'retrieved_codes': [], 'food_code': 'rice'}, 'no_evidence'),
    ({'retrieved_codes': None, 'food_code': 'rice'}, 'no_evidence'),
    ({'retrieved_codes': ['rice'], 'food_code': 'apple'}, 'no_evidence'),
    ({'retrieved_codes': ['deleted'], 'food_code': 'deleted'}, 'not_found'),
    ({'retrieved_codes': ['deleted']}, 'not_found'),
    ({'retrieved_codes': ['apple'], 'food_code': 'apple'}, 'name_mismatch'),
])
def test_unrelated_unknown_or_unretrieved_codes_never_autoselect(catalog, changes, status):
    result = resolve(catalog, **changes)
    assert result['food_code'] is None
    assert result['matched_name'] is None and result['matched_food'] is None
    assert result['match_status'] == status


def test_does_not_replace_explicitly_wrong_selection_with_another_food(catalog):
    result = resolve(catalog, retrieved_codes=['apple', 'rice'], food_code='apple')
    assert result['food_code'] is None and result['match_status'] == 'name_mismatch'


def test_raw_and_cooked_alias_ambiguity_is_preserved(catalog):
    result = resolve(catalog, name='紫薯', retrieved_codes=['steamed', 'raw', 'baked'])
    assert result['match_status'] == 'ambiguous' and result['food_code'] is None
    assert {food['code'] for food in result['candidates']} == {'steamed', 'raw', 'baked'}


@pytest.mark.parametrize('name,preparation,expected', [
    ('紫薯', '蒸熟', 'steamed'), ('紫薯', '生', 'raw'),
    ('蒸紫薯', '', 'steamed'), ('紫薯（生）', '', 'raw'),
    ('烤紫薯', '熟食', 'baked'),
])
def test_explicit_preparation_or_unambiguous_visual_name_resolves(catalog, name, preparation, expected):
    result = resolve(catalog, name=name, preparation=preparation, retrieved_codes=['steamed', 'raw', 'baked'])
    assert result['match_status'] == 'matched' and result['food_code'] == expected
    assert result['preparation'] == preparation


@pytest.mark.parametrize('changes', [
    {'name': '紫薯', 'preparation': '生鲜', 'retrieved_codes': ['steamed'], 'food_code': 'steamed'},
    {'name': '蒸紫薯', 'preparation': '生鲜', 'retrieved_codes': ['steamed']},
    {'name': '紫薯', 'preparation': '蒸熟', 'retrieved_codes': ['steamed', 'raw'], 'food_code': 'raw'},
])
def test_preparation_conflicts_do_not_silently_override_model_selection(catalog, changes):
    result = resolve(catalog, **changes)
    assert result['match_status'] == 'preparation_conflict' and result['food_code'] is None


def test_fresh_and_dried_alias_requires_preparation(catalog):
    changes = {'name': '桂圆', 'retrieved_codes': ['fresh_longan', 'dried_longan']}
    assert resolve(catalog, **changes)['match_status'] == 'ambiguous'
    assert resolve(catalog, **changes, preparation='干制')['food_code'] == 'dried_longan'


def test_retrieval_top_k_does_not_hide_an_exact_alias_ambiguity(catalog):
    result = resolve(catalog, name='桂圆', retrieved_codes=['fresh_longan'])
    assert result['food_code'] is None and result['match_status'] == 'ambiguous'
    assert {food['code'] for food in result['candidates']} == {'fresh_longan'}
    # A live database competitor can only veto, never supply an unretrieved code.
    assert resolve(catalog, name='龙眼干', retrieved_codes=['fresh_longan'])['food_code'] is None


def test_short_prepared_dish_name_disambiguates_raw_alias(catalog):
    catalog.extend([
        {**catalog[0], 'code': 'roast_duck', 'name': '烤鸭', 'preparation': '烤熟', 'aliases': ['鸭肉']},
        {**catalog[0], 'code': 'raw_duck', 'name': '鸭肉', 'preparation': '生鲜', 'aliases': ['烤鸭']},
    ])
    result = resolve(catalog, name='烤鸭', retrieved_codes=['raw_duck', 'roast_duck'])
    assert result['food_code'] == 'roast_duck'


def test_exact_name_has_priority_over_broad_alias(catalog):
    result = resolve(catalog, name='家常豆腐', retrieved_codes=['spicy_tofu', 'tofu'])
    assert result['food_code'] == 'tofu'


def test_arbitrary_substrings_are_never_a_match(catalog):
    for name in ('饭', '薯', '菜', '不知道'):
        result = resolve(catalog, name=name, retrieved_codes=[food['code'] for food in catalog])
        assert result['food_code'] is None and result['match_status'] == 'name_mismatch'


def test_candidate_objects_work_without_codes_and_drop_ai_nutrients(catalog):
    result = resolve(catalog, retrieved_codes=None, candidates=[
        {'food_code': 'rice', 'name': '白米饭', 'preparation': '煮熟', 'kcal': 999999, 'secret': 'not-public'},
    ])
    assert result['food_code'] == 'rice'
    assert result['candidates'] == [catalog[0]]
    assert 'secret' not in result['candidates'][0]


def test_explicit_empty_codes_cannot_be_overridden_by_candidate_claim(catalog):
    result = resolve(catalog, retrieved_codes=[], candidates=[{'code': 'rice'}])
    assert result['food_code'] is None and result['match_status'] == 'no_evidence'


@pytest.mark.parametrize('candidate', [
    {'code': 'rice', 'name': '旧名称'},
    {'code': 'rice', 'preparation': '生鲜'},
])
def test_stale_candidate_identity_is_rejected(catalog, candidate):
    result = resolve(catalog, candidates=[candidate], food_code='rice')
    assert result['food_code'] is None and result['match_status'] == 'stale_candidate'
    assert result['candidates'] == []


def test_changed_database_units_are_not_silently_calculated_as_100g(catalog):
    catalog[0]['basis_g'] = 1
    assert resolve(catalog)['match_status'] == 'stale_candidate'


def test_preparation_does_not_remove_nonpreparation_qualifiers(catalog):
    catalog[0].update(name='米饭（低糖）', aliases=[])
    result = resolve(catalog, name='米饭', preparation='煮熟')
    assert result['food_code'] is None and result['match_status'] == 'name_mismatch'


def test_no_input_or_catalog_mutation_and_no_shared_returned_alias_lists(catalog):
    items = [{'name': '米饭', 'estimated_grams': 120, 'retrieved_codes': ['rice']}]
    old_items, old_catalog = deepcopy(items), deepcopy(catalog)
    result = resolve_recognized_items(items, catalog)
    assert items == old_items and catalog == old_catalog
    result[0]['matched_food']['aliases'].append('changed')
    result[0]['candidates'][0]['aliases'].append('also changed')
    assert catalog == old_catalog


def test_empty_recognition_is_valid(catalog):
    assert resolve_recognized_items([], catalog) == []


def test_live_resolution_preserves_document_trace_without_replacing_db_nutrition(catalog):
    evidence={'food_code':'rice','knowledge_id':202,'source':'bisheng_document',
              'file_id':123,'chunk_index':4,'content_sha256':'c'*64,'record_sha256':'b'*64}
    result=resolve(catalog,retrieval_evidence=[evidence],snapshot_id='a'*64)
    assert result['retrieval_evidence']==[evidence]
    assert result['snapshot_id']=='a'*64
    assert result['matched_food']==catalog[0]
    result['retrieval_evidence'][0]['file_id']=999
    assert evidence['file_id']==123


@pytest.mark.parametrize('visual,canonical,state', [
    ('玉米段', '煮玉米', '煮熟'), ('土豆片', '水煮土豆', '煮熟'),
    ('土豆块', '炖土豆', '炖熟'), ('胡萝卜丝', '清炒胡萝卜', '炒熟'),
])
def test_plain_ingredient_cutting_shape_preserves_identity(catalog, visual, canonical, state):
    food={**catalog[0], 'code':'shape', 'name':canonical, 'preparation':state, 'aliases':[]}
    catalog.append(food)
    result=resolve(catalog,name=visual,preparation=state,retrieved_codes=['shape'])
    assert result['food_code']=='shape' and result['match_status']=='matched'


@pytest.mark.parametrize('visual,state,canonical,actual', [
    ('土豆片','煎熟','口蘑炒土豆片','炒熟'),
    ('玉米段','煮熟','玉米粥','煮熟'),
    ('土豆片','煎熟','水煮土豆','煮熟'),
    ('牛肉片','煎熟','孜然牛肉','炒熟'),
    ('土豆泥','即食','水煮土豆','煮熟'),
])
def test_shape_matching_never_discards_recipe_or_changes_cooking_method(catalog,visual,state,canonical,actual):
    catalog.append({**catalog[0],'code':'shape','name':canonical,'preparation':actual,'aliases':[]})
    assert resolve(catalog,name=visual,preparation=state,retrieved_codes=['shape'])['food_code'] is None


@pytest.fixture
def legacy_catalog(catalog):
    catalog.append({
        **catalog[0], 'code': 'legacy', 'name': '测试谷饭（熟）',
        'preparation': '', 'aliases': [], 'source_type': 'demo',
    })
    return catalog


@pytest.mark.parametrize('preparation', ['熟制', '熟', '熟食', '蒸熟', '煮熟', '蒸制'])
def test_generic_cooked_name_can_supply_a_cautious_legacy_reference(legacy_catalog, preparation):
    original = deepcopy(legacy_catalog)
    result = resolve(legacy_catalog, name='测试谷饭', preparation=preparation, retrieved_codes=['legacy'])
    assert result['food_code'] == 'legacy' and result['match_status'] == 'matched'
    assert result['match_note'] == 'legacy_cooked_reference'
    assert result['matched_name'] == '测试谷饭（熟）'
    assert result['matched_food']['preparation'] == ''
    assert result['matched_food']['source_type'] == 'demo'
    assert result['matched_food']['verified'] is False
    assert legacy_catalog == original


@pytest.mark.parametrize('preparation', ['炸熟', '炒熟', '烤熟', '煎熟', '炖熟', '生鲜', '干制', '即食'])
def test_generic_legacy_cooked_reference_is_not_a_cooking_method_wildcard(legacy_catalog, preparation):
    result = resolve(legacy_catalog, name='测试谷饭', preparation=preparation, retrieved_codes=['legacy'])
    assert result['food_code'] is None and result['match_status'] == 'preparation_conflict'
    assert 'match_note' not in result


def test_existing_database_preparation_is_never_overridden_by_name_annotation(legacy_catalog):
    legacy_catalog[-1]['preparation'] = '生鲜'
    result = resolve(legacy_catalog, name='测试谷饭', preparation='蒸熟', retrieved_codes=['legacy'])
    assert result['food_code'] is None and result['match_status'] == 'preparation_conflict'
    assert result['candidates'][0]['preparation'] == '生鲜'


def test_missing_metadata_without_explicit_annotation_stays_unknown(legacy_catalog):
    legacy_catalog[-1]['name'] = '测试谷饭'
    result = resolve(legacy_catalog, name='测试谷饭', preparation='蒸熟', retrieved_codes=['legacy'])
    assert result['food_code'] is None and result['match_status'] == 'preparation_conflict'


def test_explicit_raw_annotation_never_becomes_cooked_reference(legacy_catalog):
    legacy_catalog[-1]['name'] = '测试谷饭（生）'
    result = resolve(legacy_catalog, name='测试谷饭', preparation='蒸熟', retrieved_codes=['legacy'])
    assert result['food_code'] is None and result['match_status'] == 'preparation_conflict'
    raw = resolve(legacy_catalog, name='测试谷饭', preparation='生鲜', retrieved_codes=['legacy'])
    assert raw['food_code'] == 'legacy'
    assert 'match_note' not in raw and raw['matched_food']['preparation'] == ''


def test_compound_preparation_annotation_preserves_skin_and_other_qualifiers(legacy_catalog):
    legacy_catalog[-1]['name'] = '测试鸡胸肉（熟，无皮）'
    result = resolve(legacy_catalog, name='测试鸡胸肉（无皮）', preparation='煮熟', retrieved_codes=['legacy'])
    assert result['food_code'] == 'legacy' and result['match_note'] == 'legacy_cooked_reference'
    assert result['matched_food']['name'] == '测试鸡胸肉（熟，无皮）'
    for name in ('测试鸡胸肉', '测试鸡胸肉（有皮）'):
        assert resolve(legacy_catalog, name=name, preparation='煮熟', retrieved_codes=['legacy'])['food_code'] is None


def test_more_specific_equal_name_candidate_ranks_above_generic_reference(legacy_catalog):
    legacy_catalog.append({**legacy_catalog[-1], 'code': 'specific', 'name': '测试谷饭（蒸熟）', 'preparation': '蒸熟'})
    result = resolve(legacy_catalog, name='测试谷饭', preparation='蒸熟', retrieved_codes=['legacy', 'specific'])
    assert result['food_code'] == 'specific' and result['match_status'] == 'matched'
    assert 'match_note' not in result
    # A supplied selection is never silently replaced with this more specific code.
    selected = resolve(legacy_catalog, name='测试谷饭', preparation='蒸熟', retrieved_codes=['legacy', 'specific'], food_code='legacy')
    assert selected['food_code'] is None


def test_unretrieved_more_specific_competitor_can_only_veto_legacy_reference(legacy_catalog):
    legacy_catalog.append({**legacy_catalog[-1], 'code': 'specific', 'name': '测试谷饭（蒸熟）', 'preparation': '蒸熟'})
    result = resolve(legacy_catalog, name='测试谷饭', preparation='蒸熟', retrieved_codes=['legacy'])
    assert result['food_code'] is None and result['match_status'] == 'ambiguous'
    assert {food['code'] for food in result['candidates']} == {'legacy'}


def test_equal_legacy_references_remain_ambiguous_even_if_retrieval_omits_one(legacy_catalog):
    legacy_catalog.append({**legacy_catalog[-1], 'code': 'second', 'name': '测试谷饭（熟食）'})
    result = resolve(legacy_catalog, name='测试谷饭', preparation='蒸熟', retrieved_codes=['legacy'])
    assert result['food_code'] is None and result['match_status'] == 'ambiguous'


@pytest.mark.parametrize('alias,state', [
    ('炒制', '炒熟'), ('煎制', '煎熟'), ('炸制', '炸熟'),
    ('烤制', '烤熟'), ('蒸制', '蒸熟'), ('煮制', '煮熟'), ('炖制', '炖熟'),
])
def test_closed_preparation_synonyms_have_the_same_canonical_meaning(catalog, alias, state):
    catalog.append({**catalog[0], 'code': 'prepared', 'name': '测试标准菜', 'preparation': state, 'aliases': []})
    result = resolve(catalog, name='测试标准菜', preparation=alias, retrieved_codes=['prepared'])
    assert result['food_code'] == 'prepared'
    assert result['matched_food']['preparation'] == state


def test_unknown_preparation_phrase_is_not_fuzzily_reinterpreted(catalog):
    result = resolve(catalog, name='家常豆腐', preparation='随便做熟', retrieved_codes=['tofu'])
    assert result['food_code'] is None and result['match_status'] == 'preparation_conflict'
