"""Verify the expanded catalog through Nginx and a temporary account."""
import asyncio
import json
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from app.db import connect
from app.food_catalog import normalize_name, validate_food


async def cleanup(user_id):
    async with connect() as db:
        meals=await (await db.execute('SELECT id FROM meals WHERE user_id=?',(user_id,))).fetchall()
        for meal in meals:
            await db.execute('DELETE FROM meal_items WHERE meal_id=?',(meal['id'],))
        for table in ('meals','sessions','profiles'):
            await db.execute(f'DELETE FROM {table} WHERE user_id=?',(user_id,))
        await db.execute('DELETE FROM users WHERE id=?',(user_id,))
        await db.commit()


def main():
    user_id=None
    try:
        with httpx.Client(base_url='http://web',timeout=30) as client:
            account=client.post('/api/auth/register',json={
                'email':'catalog-check-'+secrets.token_hex(6)+'@example.invalid',
                'password':secrets.token_urlsafe(24)})
            account.raise_for_status();user_id=account.json()['user_id']
            response=client.get('/api/foods');response.raise_for_status()
            foods=response.json()
            assert len(foods)>=1000, f'Catalog unexpectedly small: {len(foods)}'
            names=[normalize_name(x['name']) for x in foods]
            assert len(names)==len(set(names)), 'Duplicate canonical names'
            generated=[x for x in foods if x['source_type']=='ai_estimate']
            for food in generated:
                checked=validate_food(food,food['category'])
                assert checked['code']==food['code']
                assert food['source_model'] and food['batch_id'] and food['basis_g']==100
                assert food['verified'] is False
            coverage={}
            for query in ('紫薯','酸奶','鸡块','鸭血','米饭'):
                matches=[x for x in foods if query in ' '.join([x['name'],*x['aliases']])]
                assert matches, 'Missing common food: '+query
                coverage[query]=[x['name'] for x in matches[:4]]
            selected=next(x for x in generated if '紫薯' in x['name'] and x['preparation']=='蒸熟')
            saved=client.post('/api/meals',json={'meal_type':'lunch',
                'eaten_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                'items':[{'food_code':selected['code'],'grams':150}]})
            saved.raise_for_status()
            summary=client.get('/api/nutrition/summary?days=1').json()
            expected=round(selected['kcal']*1.5,2)
            assert abs(summary['totals']['kcal']-expected)<0.011
            print(json.dumps({'catalog_total':len(foods),'ai_rows':len(generated),
                'categories':len({x['category'] for x in generated}),
                'coverage':coverage,'saved_food':selected['name'],
                'saved_kcal':summary['totals']['kcal'],
                'all_ai_rows_pass_validation':True},ensure_ascii=False),flush=True)
    finally:
        if user_id:asyncio.run(cleanup(user_id))
        print('Temporary catalog check account and meal records removed',flush=True)


if __name__=='__main__':main()
