import asyncio
import io
import json
import logging
import re
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse
from PIL import Image, ImageOps, UnidentifiedImageError

from .ai import chat_chunks, recognize_image
from .bisheng_recognition import recognize_workflow_image
from .recognition_matching import resolve_recognized_items
from .reporting import generate_report
from .auth import COOKIE, check_password, create_session, current_user, hash_password, token_digest
from .config import get_settings
from .db import INTEGRITY_ERRORS, connect, initialize
from .food_catalog import catalog_rows, initialize_catalog, match_food
from .schemas import ChatMessage, Credentials, MealCreate, ProfilePatch

log=logging.getLogger('nutrition')
settings=get_settings()
AI_SEM=asyncio.Semaphore(max(1,settings.app_max_ai_concurrency))
Image.MAX_IMAGE_PIXELS=16_000_000

@asynccontextmanager
async def lifespan(app: FastAPI):
    await initialize()
    await initialize_catalog()
    settings.app_media_dir.mkdir(parents=True,exist_ok=True)
    yield

app=FastAPI(title='AI 营养师 API',version='0.1.0',lifespan=lifespan)

@app.middleware('http')
async def origin_guard(request:Request,call_next):
    if request.method in {'POST','PUT','PATCH','DELETE'}:
        origin=request.headers.get('origin')
        # In same-origin production deployments browsers send the public Host as Origin.
        host=f'{request.url.scheme}://{request.headers.get("host", "")}'
        if origin and origin not in {settings.app_allowed_origin,host}:
            return Response('Forbidden origin',status_code=403)
    return await call_next(request)

def rowdict(r): return dict(r) if r is not None else None

def event(kind:str,data:dict) -> str:
    return f'event: {kind}\ndata: {json.dumps(data,ensure_ascii=False)}\n\n'

async def ai_slot():
    try:
        await asyncio.wait_for(AI_SEM.acquire(),timeout=1.5)
    except asyncio.TimeoutError as exc:
        raise HTTPException(429,'AI 请求繁忙，请稍后再试') from exc

@app.get('/api/health')
async def health():return {'status':'ok','demo':settings.demo_mode}

@app.get('/api/version')
async def version():return {'revision':settings.app_revision}

@app.post('/api/auth/register',status_code=201)
async def register(body:Credentials,response:Response):
    email=body.email.strip().lower()
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',email):
        raise HTTPException(422,'邮箱格式不正确')
    user_id=str(uuid.uuid4())
    async with connect() as db:
        try:
            await db.execute('INSERT INTO users(id,email,password_hash) VALUES(?,?,?)',
                             (user_id,email,hash_password(body.password)))
            await db.execute('INSERT INTO profiles(user_id) VALUES(?)',(user_id,))
            await db.commit()
        except INTEGRITY_ERRORS as exc:
            raise HTTPException(409,'邮箱已注册') from exc
    token=await create_session(user_id)
    response.set_cookie(COOKIE,token,httponly=True,secure=settings.app_cookie_secure,samesite='lax',max_age=14*86400,path='/')
    return {'user_id':user_id,'email':email}

@app.post('/api/auth/login')
async def login(body:Credentials,response:Response):
    async with connect() as db:
        cur=await db.execute('SELECT id,password_hash FROM users WHERE email=?',(body.email.strip().lower(),))
        r=await cur.fetchone()
    if not r or not check_password(body.password,r['password_hash']):
        raise HTTPException(401,'账号或密码错误')
    token=await create_session(r['id'])
    response.set_cookie(COOKIE,token,httponly=True,secure=settings.app_cookie_secure,samesite='lax',max_age=14*86400,path='/')
    return {'user_id':r['id']}

@app.post('/api/auth/logout')
async def logout(response:Response,request:Request,user:str=Depends(current_user)):
    token=request.cookies.get(COOKIE)
    async with connect() as db:
        await db.execute('DELETE FROM sessions WHERE token_hash=?',(token_digest(token),))
        await db.commit()
    response.delete_cookie(COOKIE,path='/')
    return {'ok':True}

@app.get('/api/auth/me')
async def me(user:str=Depends(current_user)):
    async with connect() as db:
        cur=await db.execute('SELECT id,email FROM users WHERE id=?',(user,))
        return rowdict(await cur.fetchone())

@app.get('/api/profile')
async def profile(user:str=Depends(current_user)):
    async with connect() as db:
        cur=await db.execute('SELECT * FROM profiles WHERE user_id=?',(user,))
        return rowdict(await cur.fetchone())

@app.put('/api/profile')
async def update_profile(body:ProfilePatch,user:str=Depends(current_user)):
    async with connect() as db:
        await db.execute('UPDATE profiles SET name=?,age=?,height_cm=?,weight_kg=?,goal=? WHERE user_id=?',
                          (body.name,body.age,body.height_cm,body.weight_kg,body.goal,user))
        await db.commit()
    return {'ok':True}

@app.get('/api/foods')
async def foods(user:str=Depends(current_user)):
    return await catalog_rows()

@app.post('/api/images',status_code=201)
async def upload_image(file:UploadFile=File(...),user:str=Depends(current_user)):
    raw=await file.read(5*1024*1024+1)
    if len(raw)>5*1024*1024: raise HTTPException(413,'图片不能超过 5MB')
    try:
        with Image.open(io.BytesIO(raw)) as pic:
            if pic.format not in {'JPEG','PNG','WEBP'}:
                raise ValueError('unsupported')
            pic=ImageOps.exif_transpose(pic)
            pic.thumbnail((2048,2048))
            pic=pic.convert('RGB')
            image_id=str(uuid.uuid4())
            out=(settings.app_media_dir/f'{image_id}.jpg').resolve()
            pic.save(out,format='JPEG',quality=84,optimize=True)
    except (UnidentifiedImageError,ValueError,OSError,Image.DecompressionBombError) as exc:
        raise HTTPException(415,'只支持合法的 JPG/PNG/WebP 图片') from exc
    async with connect() as db:
        await db.execute('INSERT INTO images(id,user_id,path,mime) VALUES(?,?,?,?)',
                         (image_id,user,str(out),'image/jpeg'))
        await db.commit()
    return {'id':image_id,'url':f'/api/images/{image_id}'}

@app.get('/api/images/{image_id}')
async def read_image(image_id:str,user:str=Depends(current_user)):
    async with connect() as db:
        cur=await db.execute('SELECT path FROM images WHERE id=? AND user_id=?',(image_id,user))
        r=await cur.fetchone()
    if not r: raise HTTPException(404,'图片不存在')
    path=Path(r['path']).resolve()
    if not path.is_file() or path.parent != settings.app_media_dir.resolve(): raise HTTPException(404,'图片不存在')
    if getattr(settings,'app_nginx_accel',False):
        return Response(headers={'X-Accel-Redirect':f'/private-media/{path.name}',
                                 'Cache-Control':'private, no-store'},media_type='image/jpeg')
    return FileResponse(path,media_type='image/jpeg',headers={'Cache-Control':'private, no-store'})

@app.post('/api/meals/recognize')
async def recognize(body:dict,user:str=Depends(current_user)):
    started=time.perf_counter()
    image_id=body.get('image_id','')
    async with connect() as db:
        cur=await db.execute('SELECT path,mime FROM images WHERE id=? AND user_id=?',(image_id,user))
        r=await cur.fetchone()
    if not r: raise HTTPException(404,'图片不存在')
    await ai_slot()
    try:
        use_workflow=settings.food_recognition_provider=='bisheng' and not settings.demo_mode
        if use_workflow:
            recognized=await recognize_workflow_image(Path(r['path']),r['mime'])
            items=resolve_recognized_items(recognized,await catalog_rows())
        else:
            items=await recognize_image(Path(r['path']),r['mime'])
            catalog=await catalog_rows()
            valid_codes={food['code'] for food in catalog}
            for item in items:
                if item.get('food_code') not in valid_codes:
                    item['food_code']=match_food(item['name'],catalog)
        elapsed_ms=round((time.perf_counter()-started)*1000)
        source='bisheng' if use_workflow else 'demo' if settings.demo_mode else 'direct'
        log.info('food_recognition source=%s elapsed_ms=%d items=%d matched=%d',source,elapsed_ms,len(items),sum(bool(x.get('food_code')) for x in items))
        return {'items':items,'source':source,'elapsed_ms':elapsed_ms,
                'notice':'已按食品库复核匹配结果，请确认菜品与分量；食品库中的 AI 估算值未经实验核验，配料和用油会影响实际营养。'}
    finally:
        AI_SEM.release()

@app.post('/api/meals',status_code=201)
async def add_meal(body:MealCreate,user:str=Depends(current_user)):
    meal_id=str(uuid.uuid4())
    codes=[x.food_code for x in body.items]
    async with connect() as db:
        if body.image_id:
            row=await (await db.execute('SELECT 1 FROM images WHERE id=? AND user_id=?',(body.image_id,user))).fetchone()
            if not row: raise HTTPException(404,'图片不存在')
        rows=await (await db.execute('SELECT * FROM foods WHERE code IN ('+','.join('?' for _ in set(codes))+')',tuple(set(codes)))).fetchall()
        by_code={r['code']:r for r in rows}
        if any(code not in by_code for code in codes): raise HTTPException(422,'请选择标准食物')
        # Normalize time to UTC; reporting uses UTC dates in this MVP.
        eaten=body.eaten_at
        if eaten.tzinfo is None: raise HTTPException(422,'eaten_at 必须包含时区')
        eaten=eaten.astimezone(timezone.utc).isoformat()
        try:
            await db.execute('INSERT INTO meals(id,user_id,meal_type,eaten_at,image_id) VALUES(?,?,?,?,?)',
                             (meal_id,user,body.meal_type,eaten,body.image_id))
            for item in body.items:
                food=by_code[item.food_code]
                vals=[round(food[k]*item.grams/100,2) for k in ('kcal','protein','fat','carbs')]
                await db.execute('INSERT INTO meal_items(id,meal_id,food_code,grams,kcal,protein,fat,carbs) VALUES(?,?,?,?,?,?,?,?)',
                                 (str(uuid.uuid4()),meal_id,item.food_code,item.grams,*vals))
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    return {'id':meal_id}

@app.get('/api/meals')
async def list_meals(day:date|None=None,user:str=Depends(current_user)):
    day=day or datetime.now(LOCAL_TZ).date()
    day_begin=datetime.combine(day,datetime.min.time(),LOCAL_TZ).astimezone(timezone.utc).isoformat()
    day_end=datetime.combine(day+timedelta(days=1),datetime.min.time(),LOCAL_TZ).astimezone(timezone.utc).isoformat()
    async with connect() as db:
        cur=await db.execute('SELECT * FROM meals WHERE user_id=? AND eaten_at>=? AND eaten_at<? ORDER BY eaten_at DESC',(user,day_begin,day_end))
        meals=[rowdict(r) for r in await cur.fetchall()]
        for meal in meals:
            cur=await db.execute('SELECT i.*, f.name FROM meal_items i JOIN foods f ON f.code=i.food_code WHERE i.meal_id=?',(meal['id'],))
            meal['items']=[rowdict(r) for r in await cur.fetchall()]
    return meals

LOCAL_TZ = ZoneInfo('Asia/Shanghai')

async def nutrition_summary_for_user(user: str, days: int) -> dict:
    """Aggregate recorded values by calendar day in Asia/Shanghai, not UTC."""
    today = datetime.now(LOCAL_TZ).date()
    first = today - timedelta(days=days - 1)
    since_utc = datetime.combine(first, datetime.min.time(), LOCAL_TZ).astimezone(timezone.utc).isoformat()
    daily = {str(first+timedelta(days=i)):
             {'day': str(first+timedelta(days=i)), 'kcal': 0.0, 'protein': 0.0,
              'fat': 0.0, 'carbs': 0.0} for i in range(days)}
    async with connect() as db:
        cur = await db.execute('''SELECT m.eaten_at, i.kcal,i.protein,i.fat,i.carbs
            FROM meals m JOIN meal_items i ON m.id=i.meal_id
            WHERE m.user_id=? AND m.eaten_at>=?''',(user,since_utc))
        for row in await cur.fetchall():
            day = datetime.fromisoformat(row['eaten_at']).astimezone(LOCAL_TZ).date().isoformat()
            if day in daily:
                for key in ('kcal','protein','fat','carbs'):
                    daily[day][key] += float(row[key])
    rows=list(daily.values())
    for row in rows:
        for key in ('kcal','protein','fat','carbs'):
            row[key]=round(row[key],2)
    totals={key:round(sum(row[key] for row in rows),2) for key in ('kcal','protein','fat','carbs')}
    return {'days': days, 'recorded_days': sum(1 for row in rows if row['kcal']>0),
            'daily': rows,'totals':totals,'timezone':'Asia/Shanghai'}

@app.get('/api/nutrition/summary')
async def summary(days:int=1,user:str=Depends(current_user)):
    if not 1<=days<=30:
        raise HTTPException(422,'days 应为 1～30')
    return await nutrition_summary_for_user(user, days)

@app.post('/api/reports/generate',status_code=201)
async def generate_nutrition_report(days:int=7,user:str=Depends(current_user)):
    if not settings.app_reports_enabled:
        raise HTTPException(503,'健康报告功能暂未启用')
    if days not in (7,30):
        raise HTTPException(422,'报告周期应为 7 或 30 天')
    computed=await nutrition_summary_for_user(user, days)
    async with connect() as db:
        profile_row=await (await db.execute('SELECT * FROM profiles WHERE user_id=?',(user,))).fetchone()
    user_profile=rowdict(profile_row) or {}
    await ai_slot()
    try:
        content=await generate_report(computed,user_profile,days)
    finally:
        AI_SEM.release()
    report_id=str(uuid.uuid4())
    source='demo' if settings.demo_mode else 'bisheng-1.3.1'
    async with connect() as db:
        await db.execute('INSERT INTO nutrition_reports(id,user_id,days,summary_json,content,source) VALUES(?,?,?,?,?,?)',
                         (report_id,user,days,json.dumps(computed,ensure_ascii=False),content,source))
        await db.commit()
    return {'id':report_id,'days':days,'content':content,'summary':computed,'source':source}

@app.get('/api/reports')
async def list_reports(user:str=Depends(current_user)):
    async with connect() as db:
        result=await (await db.execute('SELECT id,days,source,created_at FROM nutrition_reports WHERE user_id=? ORDER BY created_at DESC LIMIT 20',(user,))).fetchall()
    return [rowdict(x) for x in result]

@app.get('/api/reports/{report_id}')
async def get_report(report_id:str,user:str=Depends(current_user)):
    async with connect() as db:
        row=await (await db.execute('SELECT * FROM nutrition_reports WHERE id=? AND user_id=?',(report_id,user))).fetchone()
    if not row: raise HTTPException(404,'报告不存在')
    output=rowdict(row)
    output['summary']=json.loads(output.pop('summary_json'))
    return output

@app.post('/api/chat/stream')
async def stream_chat(body:ChatMessage,user:str=Depends(current_user)):
    async with connect() as db:
        cur=await db.execute('SELECT * FROM profiles WHERE user_id=?',(user,))
        user_profile=rowdict(await cur.fetchone()) or {}
    if not settings.demo_mode and not settings.vllm_chat_completions_url:
        raise HTTPException(503,'尚未配置 vLLM 模型接口')
    async with connect() as db:
        cur=await db.execute('SELECT role,content FROM chat_messages WHERE user_id=? AND thread_id=? ORDER BY created_at,id DESC LIMIT 12',(user,body.thread_id))
        conversation=[rowdict(r) for r in await cur.fetchall()]
        conversation.reverse()
    await ai_slot()
    async def generate():
        parts=[]
        try:
            async with connect() as db:
                await db.execute('INSERT INTO chat_messages(id,user_id,thread_id,role,content) VALUES(?,?,?,?,?)',
                                 (str(uuid.uuid4()),user,body.thread_id,'user',body.message))
                await db.commit()
            yield event('start',{'thread_id':body.thread_id})
            async for text in chat_chunks(body.message,conversation,user_profile):
                parts.append(text)
                yield event('delta',{'content':text})
            async with connect() as db:
                await db.execute('INSERT INTO chat_messages(id,user_id,thread_id,role,content) VALUES(?,?,?,?,?)',
                                 (str(uuid.uuid4()),user,body.thread_id,'assistant',''.join(parts)))
                await db.commit()
            yield event('done',{})
        except Exception:
            log.exception('upstream chat error')
            yield event('error',{'message':'咨询服务暂时不可用，请稍后再试'})
        finally:
            AI_SEM.release()
    return StreamingResponse(generate(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

@app.get('/api/chat/history')
async def history(thread_id:str,user:str=Depends(current_user)):
    if len(thread_id)>90 or not re.fullmatch(r'[\w-]+',thread_id): raise HTTPException(422,'thread_id 不合法')
    async with connect() as db:
        cur=await db.execute('SELECT role,content,created_at FROM chat_messages WHERE user_id=? AND thread_id=? ORDER BY created_at,id LIMIT 100',(user,thread_id))
        return [rowdict(r) for r in await cur.fetchall()]
