"""Release acceptance through Nginx; remove only this run's temporary account."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import secrets

import httpx

from app.db import connect


async def cleanup(user_id,email):
    async with connect() as db:
        user=await (await db.execute('SELECT email FROM users WHERE id=?',(user_id,))).fetchone()
        if not user or user['email']!=email or not email.startswith('delivery-'):
            raise RuntimeError('Temporary account identity mismatch')
        meals=await (await db.execute('SELECT id FROM meals WHERE user_id=?',(user_id,))).fetchall()
        for meal in meals:
            await db.execute('DELETE FROM meal_items WHERE meal_id=?',(meal['id'],))
        for table in ('meals','chat_messages','sessions','profiles'):
            await db.execute(f'DELETE FROM {table} WHERE user_id=?',(user_id,))
        await db.execute('DELETE FROM users WHERE id=?',(user_id,))
        await db.commit()


def run(args):
    checks=[];user_id=None
    email='delivery-'+secrets.token_hex(16)+'@example.invalid'
    try:
        with httpx.Client(base_url='http://web',timeout=100) as client:
            page=client.get('/');page.raise_for_status()
            assert '<div id="app">' in page.text
            checks.append('frontend')
            assert client.get('/api/health').json()['status']=='ok'
            assert client.get('/api/version').json()['revision']==args.revision
            checks.extend(['health','revision'])
            account=client.post('/api/auth/register',json={'email':email,'password':secrets.token_urlsafe(24)})
            account.raise_for_status();user_id=account.json()['user_id']
            identity=client.get('/api/auth/me');identity.raise_for_status()
            assert identity.json()['id']==user_id
            checks.append('authentication')
            foods=client.get('/api/foods');foods.raise_for_status();foods=foods.json()
            assert foods and all(x['kcal']>=0 for x in foods)
            food=next((x for x in foods if x['code']=='rice'),foods[0])
            checks.append('food-catalog')
            meal=client.post('/api/meals',json={'meal_type':'lunch','eaten_at':datetime.now(timezone.utc).isoformat(),
                'items':[{'food_code':food['code'],'grams':100}]})
            meal.raise_for_status()
            summary=client.get('/api/nutrition/summary?days=1').json()
            assert abs(summary['totals']['kcal']-food['kcal'])<0.02
            checks.extend(['meal-save','nutrition-summary'])
            if args.model_check:
                chat=client.post('/api/chat/stream',json={'thread_id':'delivery-check','message':'用一句话说明均衡早餐包含哪些食物。'})
                chat.raise_for_status()
                assert 'event: done' in chat.text and 'event: error' not in chat.text and 'event: delta' in chat.text
                checks.append('model-stream')
    finally:
        if user_id:
            asyncio.run(cleanup(user_id,email))
            checks.append('temporary-data-cleanup')
    print(json.dumps({'status':'passed','revision':args.revision,'checks':checks}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--revision',required=True)
    parser.add_argument('--model-check',action='store_true');run(parser.parse_args())
