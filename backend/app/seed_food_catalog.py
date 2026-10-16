"""One-shot, resumable LLM catalog generation. Raw responses remain auditable."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import re

import httpx

from .config import get_settings
from .db import connect
from .food_catalog import initialize_catalog, normalize_name, validate_food


# Each topic is deliberately bounded to diversify a one-shot generation run.
TOPICS = [
 ('谷物干料', '大米 糙米 燕麦 荞麦 藜麦 小米 黑米 薏米 玉米面'),
 ('米饭熟食', '白米饭 糙米饭 杂粮饭 藜麦饭 小米饭 黑米饭 糯米饭'),
 ('粥类', '白米粥 小米粥 八宝粥 皮蛋瘦肉粥 南瓜粥 银耳粥'),
 ('面条粉皮熟食', '清水面条 荞麦面 米线 河粉 粉丝 红薯粉 魔芋面'),
 ('馒头包子花卷', '馒头 全麦馒头 花卷 豆沙包 肉包 菜包 糖三角'),
 ('饼类早餐', '油条 煎饼 鸡蛋饼 葱油饼 烧饼 手抓饼 窝窝头'),
 ('面包', '吐司 全麦面包 法棍 贝果 软欧包 牛角包 黑麦面包'),
 ('糕点蛋糕', '戚风蛋糕 奶油蛋糕 蛋挞 月饼 绿豆糕 桃酥'),
 ('薯芋生鲜', '紫薯 红薯 马铃薯 芋头 山药 木薯 凉薯 菊芋'),
 ('薯芋熟食', '蒸紫薯 蒸红薯 烤红薯 水煮土豆 蒸芋头 蒸山药 土豆泥'),
 ('干豆杂豆', '黄豆 黑豆 红豆 绿豆 鹰嘴豆 扁豆 芸豆 蚕豆'),
 ('熟豆食品', '水煮黄豆 水煮毛豆 红豆沙 绿豆沙 炖芸豆 鹰嘴豆泥'),
 ('豆腐豆制品', '北豆腐 南豆腐 内酯豆腐 豆腐干 千张 腐竹 素鸡 油豆腐'),
 ('叶菜生鲜', '菠菜 油麦菜 生菜 小白菜 苋菜 空心菜 茼蒿 芥蓝'),
 ('叶菜熟食', '清炒菠菜 蒜蓉油麦菜 白灼生菜 清炒小白菜 蒜蓉空心菜'),
 ('瓜茄生鲜', '冬瓜 南瓜 西葫芦 黄瓜 苦瓜 丝瓜 茄子 番茄 彩椒'),
 ('瓜茄熟食', '清炒冬瓜 蒸南瓜 清炒西葫芦 凉拌黄瓜 清炒丝瓜 烧茄子'),
 ('根茎花菜生鲜', '胡萝卜 白萝卜 莲藕 莴笋 茭白 西兰花 菜花 芦笋'),
 ('根茎花菜熟食', '清炒胡萝卜 炖白萝卜 清炒藕片 莴笋丝 清炒西兰花'),
 ('菌菇生鲜', '香菇 平菇 金针菇 杏鲍菇 口蘑 蟹味菇 茶树菇 羊肚菌'),
 ('菌菇熟食', '炒香菇 清炒平菇 白灼金针菇 煎杏鲍菇 口蘑炒青菜'),
 ('海藻木耳笋类', '海带 紫菜 裙带菜 黑木耳 银耳 竹笋 冬笋 春笋'),
 ('温带鲜果', '苹果 香蕉 梨 桃 杏 李子 樱桃 葡萄 草莓 蓝莓 猕猴桃'),
 ('热带柑橘瓜果', '橙子 橘子 柚子 菠萝 芒果 木瓜 火龙果 西瓜 哈密瓜'),
 ('果干果脯', '葡萄干 红枣 桂圆干 无花果干 杏干 蔓越莓干 苹果干'),
 ('坚果', '核桃 杏仁 巴旦木 腰果 开心果 榛子 松子 碧根果 夏威夷果'),
 ('种子与栗类', '南瓜子 葵花子 西瓜子 芝麻 奇亚籽 亚麻籽 板栗 花生'),
 ('猪肉生鲜', '猪里脊 猪五花 猪后腿肉 猪前腿肉 猪排骨 猪蹄 猪肝'),
 ('猪肉熟食', '水煮猪里脊 白切五花肉 熟猪排骨 酱猪蹄 卤猪耳朵'),
 ('牛羊肉生鲜', '牛里脊 牛腱 牛腩 牛肋条 羊腿肉 羊排 羊里脊'),
 ('牛羊肉熟食', '酱牛肉 清炖牛腩 熟牛腱 烤牛排 水煮羊肉 炖羊排'),
 ('禽肉生鲜', '鸡胸肉 鸡腿肉 鸡翅 鸡皮 鸭胸 鸭腿 鹅肉 鸽子肉'),
 ('禽肉熟食', '水煮鸡胸肉 白切鸡 蒸鸡腿 烤鸡翅 烤鸭 盐水鸭 清炖鹅肉'),
 ('内脏血制品', '鸭血 猪血 鸡血 猪肝 牛肝 鸡肝 鸡心 鸭胗 猪肚'),
 ('猪肉家常菜', '炒肉片 回锅肉 鱼香肉丝 宫保肉丁 红烧肉 糖醋里脊 青椒肉丝'),
 ('牛羊肉家常菜', '番茄牛腩 土豆炖牛肉 孜然羊肉 葱爆羊肉 青椒牛柳'),
 ('鸡鸭家常菜', '花生烧鸡块 宫保鸡丁 土豆烧鸡 香菇滑鸡 黄焖鸡 啤酒鸭'),
 ('鱼类生鲜', '草鱼 鲤鱼 鲫鱼 鲈鱼 鳕鱼 三文鱼 带鱼 黄鱼 金枪鱼'),
 ('鱼类熟食', '清蒸鲈鱼 清蒸鳕鱼 煎三文鱼 红烧带鱼 烤鲭鱼 水煮鲫鱼'),
 ('虾蟹贝类生鲜', '对虾 河虾 皮皮虾 螃蟹 梭子蟹 扇贝 蛤蜊 牡蛎 贻贝'),
 ('虾蟹贝类熟食', '白灼虾 水煮蟹 蒸扇贝 蒜蓉蛤蜊 烤生蚝 水煮贻贝'),
 ('海鲜家常菜', '虾仁炒蛋 西兰花虾仁 油焖大虾 葱姜炒蟹 蒜蓉粉丝扇贝'),
 ('蛋及蛋制品', '鸡蛋 鸭蛋 鹌鹑蛋 鹅蛋 水煮鸡蛋 煎鸡蛋 咸鸭蛋 皮蛋'),
 ('蛋类家常菜', '番茄炒蛋 韭菜炒鸡蛋 虾仁蒸蛋 香椿炒蛋 鸡蛋羹'),
 ('牛奶乳饮品', '全脂牛奶 低脂牛奶 脱脂牛奶 羊奶 无乳糖牛奶 可可奶'),
 ('酸奶发酵乳', '酸奶 原味酸奶 无糖酸奶 希腊酸奶 脱脂酸奶 草莓酸奶'),
 ('奶酪奶制甜品', '切达奶酪 马苏里拉奶酪 奶油奶酪 干酪 布丁 双皮奶'),
 ('油脂', '花生油 菜籽油 大豆油 橄榄油 玉米油 芝麻油 黄油 猪油'),
 ('糖及调味品', '白砂糖 红糖 蜂蜜 糖浆 酱油 生抽 老抽 米醋 蚝油'),
 ('酱料与腌菜', '芝麻酱 花生酱 番茄酱 沙拉酱 豆瓣酱 酸菜 泡菜 榨菜'),
 ('豆腐素菜', '麻婆豆腐 家常豆腐 红烧豆腐 凉拌豆腐 香干炒芹菜 腐竹炒木耳'),
 ('混合蔬菜菜肴', '冬瓜炒鸭血 地三鲜 什锦蔬菜 荷塘小炒 蒜蓉粉丝娃娃菜'),
 ('凉拌菜', '凉拌木耳 凉拌海带 凉拌三丝 凉拌藕片 凉拌豆芽 拍黄瓜'),
 ('清汤炖汤', '紫菜蛋花汤 番茄蛋汤 冬瓜排骨汤 菌菇汤 萝卜牛肉汤'),
 ('羹类浓汤', '玉米羹 银耳羹 海鲜羹 南瓜浓汤 奶油蘑菇汤 酸辣汤'),
 ('炒饭盖饭', '蛋炒饭 扬州炒饭 咖喱鸡饭 卤肉饭 红烧牛肉盖饭 海南鸡饭'),
 ('汤面拌面', '牛肉面 番茄鸡蛋面 炸酱面 热干面 担担面 葱油拌面'),
 ('米粉米线粉类菜', '过桥米线 桂林米粉 螺蛳粉 炒河粉 酸辣粉 越南牛肉粉'),
 ('饺子馄饨烧麦', '猪肉白菜饺子 韭菜鸡蛋饺子 虾仁饺子 小馄饨 烧麦 小笼包'),
 ('火锅麻辣烫熟食', '熟火锅牛肉 熟鱼丸 熟虾滑 熟肥牛卷 熟午餐肉 熟蟹棒'),
 ('西式快餐', '牛肉汉堡 鸡肉汉堡 芝士披萨 炸鸡翅 薯条 三明治 热狗'),
 ('日式韩式餐食', '寿司 三文鱼饭团 亲子丼 鳗鱼饭 石锅拌饭 韩式炸鸡'),
 ('东南亚简餐', '越南春卷 泰式炒河粉 咖喱鸡 叻沙 冬阴功汤 菠萝炒饭'),
 ('地方小吃', '肠粉 凉皮 肉夹馍 羊肉泡馍 生煎包 锅贴 臭豆腐'),
 ('饼干零食', '苏打饼干 全麦饼干 曲奇 威化 蛋卷 米饼 桃酥 沙琪玛'),
 ('膨化肉类零食', '薯片 爆米花 虾条 锅巴 牛肉干 猪肉脯 鱿鱼丝 海苔'),
 ('巧克力糖果', '黑巧克力 牛奶巧克力 白巧克力 软糖 硬糖 牛轧糖 棉花糖'),
 ('冰品', '原味冰淇淋 巧克力冰淇淋 冰棍 雪糕 水果雪葩 冰沙'),
 ('果汁及软饮', '橙汁 苹果汁 葡萄汁 椰子水 可乐 雪碧 无糖汽水 柠檬水'),
 ('茶咖啡饮品', '绿茶 红茶 乌龙茶 美式咖啡 拿铁 卡布奇诺 摩卡 抹茶拿铁'),
 ('奶茶甜饮', '原味奶茶 珍珠奶茶 低糖奶茶 红豆奶茶 椰果奶茶 水果茶'),
 ('豆饮植物奶', '无糖豆浆 甜豆浆 黑豆浆 燕麦奶 杏仁奶 椰奶 核桃乳'),
]

SYSTEM = '''你负责生成面向中国成年人日常饮食记录的AI估算食品库。这不是官方或实测数据库，不能伪造文献、品牌营养标签或实验来源。
所有营养值都必须是每100克可食部分的典型估算，饮料同样换算为每100克而不是100毫升。kcal是千卡，protein/fat/carbs是克。不要提供每份数据。
区分生、熟、干制状态；食物名称必须清楚包含必要的生熟状态。复合菜按普通家庭常见做法估算，不虚构精确配方。不要生成药物、特殊医疗配方、营养补充剂、酒精饮料。
不得靠重复同一食物的拼写、份量、品牌或微小糖量变化凑数。名称用常见中文，aliases为1到5个常用名称/识别同义词（不含括号状态），避免把不同食品写为同义词。
每项使用紧凑数组，顺序固定为[name,preparation,basis_g,kcal,protein,fat,carbs,aliases]，不要重复输出字段名。preparation只能为：生鲜、煮熟、蒸熟、炒熟、煎熟、烤熟、炸熟、炖熟、干制、即食、饮用、烘焙。basis_g必须为数字100。
全部数值为有限非负数，每种宏量营养素不超过100，三种相加不超过100克。能量与4*protein+9*fat+4*carbs大致一致。未知食品不要捏造，换成你有把握的常见食品。
只输出紧凑JSON对象，例如 {"foods":[["白米饭","煮熟",100,116,2.6,0.3,25.6,["米饭","白饭"]]]}，不要解释、不要Markdown。'''


async def run(args):
    s = get_settings()
    if s.demo_mode or not s.vllm_chat_completions_url:
        raise RuntimeError('A real configured model is required')
    await initialize_catalog()
    root = s.app_media_dir.parent / 'food_catalog' / args.batch_id
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    async with connect() as db:
        existing = [dict(r) for r in await (await db.execute('SELECT * FROM foods')).fetchall()]
        previous = await (await db.execute('SELECT COUNT(*) AS total FROM food_metadata WHERE batch_id=?', (args.batch_id,))).fetchone()
    snapshot = root / 'foods_before.json'
    if not snapshot.exists():
        snapshot.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding='utf-8')
    known = {normalize_name(x['name']) for x in existing}
    stats = {'batch_id': args.batch_id, 'model': s.vllm_model, 'topics': len(TOPICS),
             'completed': 0, 'inserted': int(previous['total']), 'duplicates': 0, 'rejected': 0, 'failed': []}
    config = {'target_per_topic': args.count, 'concurrency': args.concurrency,
              'max_tokens': args.max_tokens, 'basis_g': 100, 'source_type': 'ai_estimate'}
    insert = 'INSERT IGNORE' if s.app_db_engine == 'mysql' else 'INSERT OR IGNORE'
    async with connect() as db:
        await db.execute(insert+' INTO food_import_batches(id,model,status,config_json,stats_json) VALUES(?,?,?,?,?)',
                         (args.batch_id, s.vllm_model, 'running', json.dumps(config), json.dumps(stats)))
        stored=await (await db.execute('SELECT model FROM food_import_batches WHERE id=?',(args.batch_id,))).fetchone()
        if stored['model'] != s.vllm_model:
            raise ValueError('A batch cannot mix responses from different models')
        await db.execute('UPDATE food_import_batches SET status=?,config_json=? WHERE id=?',
                         ('running',json.dumps(config),args.batch_id))
        await db.commit()
    lock, sem = asyncio.Lock(), asyncio.Semaphore(args.concurrency)

    async def publish():
        (root / 'progress.json').write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding='utf-8')
        async with connect() as db:
            await db.execute('UPDATE food_import_batches SET stats_json=? WHERE id=?',
                             (json.dumps(stats, ensure_ascii=False), args.batch_id))
            await db.commit()

    async with httpx.AsyncClient(timeout=httpx.Timeout(240, connect=10)) as client:
        async def topic(index, category, anchors):
            async with sem:
                output = root / f'{index:03d}.json'
                try:
                    if output.exists():
                        body = json.loads(output.read_text(encoding='utf-8'))
                    else:
                        body = None
                        for attempt in range(3):
                            try:
                                response = await client.post(s.vllm_chat_completions_url,
                                    headers={'Authorization': 'Bearer '+(s.vllm_api_key or 'EMPTY')},
                                    json={'model': s.vllm_model, 'messages': [
                                        {'role':'system','content':SYSTEM},
                                        {'role':'user','content':f'类别：{category}。生成{args.count}种不同的常见食品。优先包括：{anchors}。再补充同类别常见食品，避免跨类别。'}],
                                        'temperature':0.3,'max_tokens':args.max_tokens,
                                        'chat_template_kwargs':{'enable_thinking':False},
                                        'response_format':{'type':'json_object'}})
                                response.raise_for_status()
                                payload = response.json()
                                (root / f'{index:03d}-response.json').write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
                                choice = payload['choices'][0]
                                if choice.get('finish_reason') == 'length':
                                    raise ValueError('truncated model output')
                                body = json.loads(choice['message']['content'])
                                if not isinstance(body.get('foods'), list) or not body['foods']:
                                    raise ValueError('missing food list')
                                output.write_text(json.dumps(body,ensure_ascii=False,indent=2),encoding='utf-8')
                                break
                            except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
                                if attempt == 2:
                                    raise
                                await asyncio.sleep(2 * (attempt + 1))
                    valid, rejected = [], []
                    for item in body['foods']:
                        try:
                            if isinstance(item, list):
                                if len(item) != 8:
                                    raise ValueError('food array must contain eight fields')
                                item = dict(zip(('name','preparation','basis_g','kcal','protein','fat','carbs','aliases'), item))
                            valid.append(validate_food(item, category))
                        except ValueError as exc:
                            rejected.append({'item':item,'reason':str(exc)})
                    if rejected:
                        (root / f'{index:03d}-rejected.json').write_text(json.dumps(rejected,ensure_ascii=False,indent=2),encoding='utf-8')
                    async with lock:
                        added = duplicates = 0
                        async with connect() as db:
                            for item in valid:
                                key = normalize_name(item['name'])
                                if key in known:
                                    duplicates += 1
                                    continue
                                if args.apply:
                                    await db.execute(insert+' INTO foods(code,name,kcal,protein,fat,carbs) VALUES(?,?,?,?,?,?)',
                                        tuple(item[k] for k in ('code','name','kcal','protein','fat','carbs')))
                                    await db.execute(insert+''' INTO food_metadata(food_code,category,preparation,
                                        aliases_json,source_type,source_model,batch_id,basis_g,verified)
                                        VALUES(?,?,?,?,?,?,?,?,?)''', (item['code'],category,item['preparation'],
                                        json.dumps(item['aliases'],ensure_ascii=False),'ai_estimate',s.vllm_model,args.batch_id,100,0))
                                known.add(key)
                                added += 1
                            await db.commit()
                        stats['completed'] += 1
                        stats['inserted'] += added
                        stats['duplicates'] += duplicates
                        stats['rejected'] += len(rejected)
                        await publish()
                        print(f'[{stats["completed"]}/{len(TOPICS)}] {category}: added={added}, duplicate={duplicates}, rejected={len(rejected)}, total_added={stats["inserted"]}',flush=True)
                except Exception as exc:
                    async with lock:
                        stats['failed'].append({'category':category,'error':type(exc).__name__})
                        await publish()
                    print(f'FAILED {category}: {type(exc).__name__}',flush=True)
        await asyncio.gather(*(topic(i,*entry) for i,entry in enumerate(TOPICS)))
    stats['finished_at'] = datetime.now(timezone.utc).isoformat()
    stats['status'] = 'partial' if stats['failed'] else 'complete'
    async with connect() as db:
        await db.execute('UPDATE food_import_batches SET status=?,stats_json=? WHERE id=?',
                         (stats['status'],json.dumps(stats,ensure_ascii=False),args.batch_id))
        await db.commit()
    (root / 'progress.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(stats,ensure_ascii=False),flush=True)
    if stats['failed']:
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply',action='store_true',help='Write validated candidates to the configured database')
    parser.add_argument('--batch-id',default='qwen-foods-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))
    parser.add_argument('--count',type=int,default=30)
    parser.add_argument('--concurrency',type=int,default=3)
    parser.add_argument('--max-tokens',type=int,default=6000)
    options = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', options.batch_id):
        parser.error('batch-id must be 1..64 letters, digits, underscores or hyphens')
    if not 1 <= options.concurrency <= 4 or not 10 <= options.count <= 50 or not 2000 <= options.max_tokens <= 16000:
        parser.error('concurrency=1..4, count=10..50, max-tokens=2000..16000 required')
    asyncio.run(run(options))
