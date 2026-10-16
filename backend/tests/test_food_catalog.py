import asyncio
import copy
from types import SimpleNamespace

import pytest

from app import db
from app.food_catalog import catalog_rows, initialize_catalog, match_food, normalize_name, validate_food


def candidate():
    return {'name':'紫薯（蒸熟）','preparation':'蒸熟','basis_g':100,
            'kcal':100,'protein':1.5,'fat':0.2,'carbs':23,'aliases':['紫薯','蒸紫薯']}


def test_food_validation_and_stable_codes():
    first=validate_food(candidate(),'薯芋熟食')
    second=validate_food(candidate(),'其他类别')
    assert first['code']==second['code']
    assert first['basis_g']==100 and first['aliases']==['紫薯','蒸紫薯']
    assert normalize_name('紫薯（蒸熟）')==normalize_name(' 紫薯(蒸熟) ')
    raw=candidate();raw.update(name='紫薯（生）',preparation='生鲜')
    assert validate_food(raw,'薯芋生鲜')['code']!=first['code']
    fruit=candidate();fruit.update(name='梨',preparation='生鲜',aliases=['雪梨'])
    assert validate_food(fruit,'鲜果')['name']=='梨'


@pytest.mark.parametrize(('key','value'),[
    ('kcal',float('nan')),('kcal',float('inf')),('kcal',-1),('protein',True),
    ('fat',101),('carbs','23'),('basis_g',1),('preparation','未知'),
    ('name',''),('aliases',{'name':'紫薯'}),('kcal',800),
])
def test_invalid_model_data_is_rejected(key,value):
    food=candidate();food[key]=value
    with pytest.raises(ValueError):validate_food(food,'薯芋熟食')


def test_macro_mass_is_checked():
    food=candidate();food.update(kcal=800,protein=70,fat=60,carbs=30)
    with pytest.raises(ValueError,match='exceed'):validate_food(food,'其他')


def test_optional_model_alias_formats():
    food=candidate();food['aliases']=None
    assert validate_food(food,'薯芋熟食')['aliases']==[]
    food['aliases']='紫薯、蒸紫薯'
    assert validate_food(food,'薯芋熟食')['aliases']==['紫薯','蒸紫薯']


def test_matching_respects_preparation_and_ambiguity():
    cooked=validate_food(candidate(),'薯芋熟食')
    raw=copy.deepcopy(cooked);raw.update(code='raw',name='紫薯（生）',preparation='生鲜')
    assert match_food('紫薯',[raw,cooked])==cooked['code']
    assert match_food('紫薯（生）',[raw,cooked])=='raw'
    other=copy.deepcopy(cooked);other.update(code='baked',name='紫薯（烤熟）',preparation='烤熟')
    assert match_food('紫薯',[cooked,other]) is None
    assert match_food('蒸紫薯',[raw,cooked])==cooked['code']
    assert match_food('薯',[raw,cooked]) is None
    raw['name']='紫薯'
    cooked['name']='蒸紫薯'
    assert match_food('紫薯',[raw,cooked])==cooked['code']
    other['name']='烤紫薯'
    assert match_food('紫薯',[raw,cooked,other]) is None


def test_catalog_schema_is_idempotent_and_sources_are_preserved(monkeypatch,tmp_path):
    monkeypatch.setattr(db,'get_settings',lambda:SimpleNamespace(
        app_db_engine='sqlite',app_db_path=tmp_path/'catalog.sqlite3'))
    async def scenario():
        await db.initialize()
        await initialize_catalog()
        await initialize_catalog()
        item=validate_food(candidate(),'薯芋熟食')
        async with db.connect() as connection:
            await connection.execute('INSERT INTO foods(code,name,kcal,protein,fat,carbs) VALUES(?,?,?,?,?,?)',
                tuple(item[k] for k in ('code','name','kcal','protein','fat','carbs')))
            await connection.execute('''INSERT INTO food_metadata(food_code,category,preparation,aliases_json,
                source_type,source_model,batch_id) VALUES(?,?,?,?,?,?,?)''',
                (item['code'],'薯芋熟食','蒸熟','["紫薯","蒸紫薯"]','ai_estimate','test-model','test-batch'))
            await connection.commit()
        rows=await catalog_rows()
        assert len(rows)==11
        generated=next(x for x in rows if x['code']==item['code'])
        assert generated['source_type']=='ai_estimate' and generated['verified'] is False
        assert generated['basis_g']==100 and generated['aliases']==['紫薯','蒸紫薯']
        legacy=next(x for x in rows if x['code']=='rice')
        assert legacy['source_type']=='demo' and legacy['kcal']==116
    asyncio.run(scenario())
