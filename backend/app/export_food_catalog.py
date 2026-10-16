"""Export the database catalog and provenance for review and repeatable delivery."""
import argparse
import asyncio
from collections import Counter
import csv
import json
from pathlib import Path

from .config import get_settings
from .food_catalog import catalog_rows


async def export(batch_id):
    rows=await catalog_rows()
    root=get_settings().app_media_dir.parent/'food_catalog'/batch_id
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    (root/'catalog.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    fields=['code','name','category','preparation','basis_g','kcal','protein','fat','carbs',
            'aliases','source_type','source_model','batch_id','verified']
    with (root/'catalog.csv').open('w',encoding='utf-8-sig',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=fields,extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({**row,'aliases':'、'.join(row['aliases'])})
    summary={'total':len(rows),'by_category':dict(Counter(x['category'] for x in rows)),
             'by_source':dict(Counter(x['source_type'] for x in rows)),
             'unverified':sum(not x['verified'] for x in rows),
             'basis_g':100,'nutrition_units':{'kcal':'kcal','protein':'g','fat':'g','carbs':'g'}}
    (root/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--batch-id',required=True)
    args=parser.parse_args()
    if not args.batch_id or Path(args.batch_id).name!=args.batch_id or args.batch_id in {'.','..'}:
        parser.error('batch-id must be a directory name')
    asyncio.run(export(args.batch_id))
