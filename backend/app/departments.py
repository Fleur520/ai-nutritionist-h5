"""A small, generic outpatient directory; hospital availability varies."""
from .db import connect

SOURCE = 'https://www.nhc.gov.cn/yzygj/c100068/201610/797d49b9ca11437492bafc2d3b5cacb7/files/1732873648586_56991.pdf'
DEPARTMENTS = [
 ('general','全科医学科'),('internal','内科'),('respiratory','呼吸内科'),('digestive','消化内科'),
 ('cardiology','心血管内科'),('neurology','神经内科'),('endocrine','内分泌科'),('renal','肾内科'),
 ('surgery','普通外科'),('orthopedics','骨科'),('urology','泌尿外科'),('gynecology','妇科'),
 ('obstetrics','产科'),('pediatrics','儿科'),('dermatology','皮肤科'),('ophthalmology','眼科'),
 ('ent','耳鼻咽喉科'),('dentistry','口腔科'),('infectious','感染科'),('psychiatry','精神科'),
 ('emergency','急诊科')]

SCHEMA = 'CREATE TABLE IF NOT EXISTS triage_departments (code VARCHAR(64) CHARACTER SET ascii PRIMARY KEY, name VARCHAR(100) NOT NULL, source VARCHAR(500) NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin'

async def initialize_departments():
    async with connect() as db:
        await db.execute(SCHEMA)
        await db.executemany('INSERT IGNORE INTO triage_departments(code,name,source) VALUES(?,?,?)', [(code,name,SOURCE) for code,name in DEPARTMENTS])
        await db.commit()

async def list_departments():
    async with connect() as db:
        cur = await db.execute('SELECT code,name FROM triage_departments ORDER BY code')
        return [dict(row) for row in await cur.fetchall()]
