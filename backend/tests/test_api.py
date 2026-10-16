import os
import tempfile
from pathlib import Path

# Important: set all settings before importing app.
_TEMP=tempfile.TemporaryDirectory()
os.environ['APP_DB_PATH']=str(Path(_TEMP.name)/'db.sqlite3')
os.environ['APP_MEDIA_DIR']=str(Path(_TEMP.name)/'media')
os.environ['DEMO_MODE']='true'
os.environ['APP_COOKIE_SECURE']='false'

from fastapi.testclient import TestClient
from app.main import app

def test_end_to_end():
    with TestClient(app) as client:
        assert client.get('/api/health').status_code==200
        r=client.post('/api/auth/register',json={'email':'example@example.com','password':'safe_password_123'})
        assert r.status_code==201,r.text
        foods=client.get('/api/foods').json()
        assert any(x['code']=='rice' for x in foods)
        assert client.put('/api/profile',json={'name':'Test','age':28,'height_cm':170,'weight_kg':70,'goal':'balanced'}).status_code==200
        resp=client.post('/api/meals',json={'meal_type':'lunch','eaten_at':'2026-10-16T12:00:00+00:00','items':[{'food_code':'rice','grams':100}]})
        assert resp.status_code==201,resp.text
        assert client.get('/api/meals',params={'day':'2026-10-16'}).json()[0]['items'][0]['kcal']==116
        chat=client.post('/api/chat/stream',json={'message':'如何安排早餐?','thread_id':'thread-demo'})
        assert 'event: done' in chat.text
        assert client.get('/api/chat/history',params={'thread_id':'thread-demo'}).status_code==200
        assert client.post('/api/auth/logout').status_code==200
        assert client.get('/api/auth/me').status_code==401


def test_image_upload_is_private_and_invalid_food_rejected():
    import io
    from PIL import Image
    image=Image.new('RGB',(40,40),'orange')
    buf=io.BytesIO();image.save(buf,format='PNG')
    with TestClient(app) as client:
        user1='first@example.com';user2='second@example.com'
        assert client.post('/api/auth/register',json={'email':user1,'password':'longpassword12'}).status_code==201
        r=client.post('/api/images',files={'file':('food.png',buf.getvalue(),'image/png')})
        assert r.status_code==201,r.text
        image_id=r.json()['id']
        assert client.get('/api/images/'+image_id).status_code==200
        recognition=client.post('/api/meals/recognize',json={'image_id':image_id})
        assert recognition.status_code==200
        assert len(recognition.json()['items'])==3
        assert client.post('/api/meals',json={'meal_type':'lunch','eaten_at':'2026-10-16T12:00:00+08:00','image_id':image_id,'items':[{'food_code':'fake','grams':100}]}).status_code==422
        assert client.post('/api/auth/register',json={'email':user2,'password':'longpassword12'}).status_code==201
        assert client.get('/api/images/'+image_id).status_code==404
        assert client.post('/api/meals/recognize',json={'image_id':image_id}).status_code==404


def test_auth_and_origin_guard():
    with TestClient(app) as client:
        assert client.get('/api/profile').status_code==401
        assert client.post('/api/auth/register',json={'email':'bademail','password':'strongpass123'}).status_code==422
        response=client.post('/api/auth/login',headers={'Origin':'https://evil.example'},json={'email':'test@example.com','password':'wrongpassword'})
        assert response.status_code==403


def test_nutrition_report_demo_and_user_isolation():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    with TestClient(app) as client:
        assert client.post('/api/auth/register', json={'email':'report-a@example.com','password':'longpassword12'}).status_code == 201
        now=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
        assert client.post('/api/meals',json={
            'meal_type':'lunch','eaten_at':now,
            'items':[{'food_code':'rice','grams':150}]
        }).status_code==201
        res=client.post('/api/reports/generate?days=7')
        assert res.status_code==201,res.text
        report=res.json()
        assert report['source']=='demo'
        assert report['summary']['recorded_days']==1
        assert report['summary']['totals']['kcal']==174.0
        assert '演示' in report['content']
        assert client.get('/api/reports/'+report['id']).status_code==200
        assert len(client.get('/api/reports').json())>=1
        assert client.post('/api/reports/generate?days=12').status_code==422
        assert client.post('/api/auth/register',json={'email':'report-b@example.com','password':'longpassword12'}).status_code==201
        assert client.get('/api/reports/'+report['id']).status_code==404
