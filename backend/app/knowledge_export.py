"""Read-only food catalog snapshots for a retrieval knowledge base.

Run ``python -m app.knowledge_export --output /private/food-index/snapshot``.
In a checkout, choose a Git-ignored directory such as ``.delivery/knowledge``.
Generated catalog contents and manifests must not be committed. This module
exports only the public food fields below, never application users or meals.
The database remains authoritative for nutrition and recognition results.
"""

import argparse
import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile


FIELDS = (
    'code', 'name', 'kcal', 'protein', 'fat', 'carbs', 'category',
    'preparation', 'aliases', 'source_type', 'source_model', 'batch_id',
    'basis_g', 'verified',
)
RECORD_SEPARATOR = '\n\n<<<NUTRITIONIST_FOOD_RECORD_END>>>\n\n'
FILENAMES = ('food_documents.jsonl', 'food_catalog.txt', 'qa_records.jsonl',
             'bisheng_document_batches.json', 'manifest.json')
UNITS = {'kcal': 'kcal/100g', 'protein': 'g/100g', 'fat': 'g/100g', 'carbs': 'g/100g'}


def canonical(value):
    """A stable UTF-8 JSON representation without silently accepting NaN."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def sha256(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def normalize_rows(rows):
    """Copy the food whitelist verbatim; validate rather than repair records."""
    if not isinstance(rows, list) or not rows:
        raise ValueError('A non-empty catalog list is required')
    normalized = []
    codes = set()
    text_fields = ('code', 'name', 'category', 'preparation', 'source_type', 'source_model', 'batch_id')
    for row in rows:
        if not isinstance(row, dict) or any(field not in row for field in FIELDS):
            raise ValueError('Missing required food catalog fields')
        if any(not isinstance(row[field], str) for field in text_fields):
            raise ValueError('Food names, codes, preparation and provenance must be text')
        if not row['code'].strip() or not row['name'].strip():
            raise ValueError('Food code and name must not be empty')
        if row['code'] in codes:
            raise ValueError(f'Duplicate food code: {row["code"]}')
        codes.add(row['code'])
        if isinstance(row['basis_g'], bool) or row['basis_g'] != 100:
            raise ValueError('Nutrition basis must be 100g of edible portion')
        if not isinstance(row['verified'], bool):
            raise ValueError('The verified flag must be a boolean')
        if row['source_type'] == 'ai_estimate' and row['verified']:
            raise ValueError('AI estimates must remain unverified')
        for field in UNITS:
            value = row[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f'Invalid food nutrient: {field}')
        if not isinstance(row['aliases'], list) or any(not isinstance(alias, str) for alias in row['aliases']):
            raise ValueError('Food aliases must be a list of strings')
        # A dedicated delimiter is only safe if it cannot occur inside a food.
        if RECORD_SEPARATOR.strip() in canonical({field: row[field] for field in FIELDS}):
            raise ValueError('Food data contains the reserved record separator')
        normalized.append({field: list(row[field]) if field == 'aliases' else row[field] for field in FIELDS})
    return sorted(normalized, key=lambda row: row['code'])


def build_documents(rows):
    """Return self-contained records and a content-addressed catalog version."""
    normalized = normalize_rows(rows)
    snapshot_id = sha256(canonical(normalized))
    documents = []
    for row in normalized:
        record_hash = sha256(canonical(row))
        metadata = {field: row[field] for field in (
            'code', 'name', 'category', 'preparation', 'basis_g', 'source_type',
            'source_model', 'batch_id', 'verified',
        )}
        metadata.update(food_code=row['code'], record_sha256=record_hash,
                        snapshot_id=snapshot_id, origin='nutritionist_db')
        content = '\n'.join((
            f'食物名称：{row["name"]}',
            f'数据库唯一食品代码 food_code：{row["code"]}',
            f'常用别名：{"、".join(row["aliases"]) or "无"}',
            f'食品类别：{row["category"]}',
            f'制作/生熟状态 preparation：{row["preparation"] or "未知（原数据未填写）"}',
            '营养基准：每100克可食部分（不是每份；饮品也按100克而非100毫升）',
            f'每100克能量：{row["kcal"]} 千卡（kcal）',
            f'每100克蛋白质：{row["protein"]} 克；脂肪：{row["fat"]} 克；碳水化合物：{row["carbs"]} 克',
            f'数据来源 source_type：{row["source_type"]}',
            f'核验状态 verified：{int(row["verified"])}（{"已核验" if row["verified"] else "未经核验"}）',
            f'生成模型 source_model：{row["source_model"] or "未记录"}',
            f'生成批次 batch_id：{row["batch_id"] or "未记录"}',
            '使用规则：只做候选检索；不将别名相同当作菜品相同；生熟不明或多候选不能强行选择；以业务数据库最新记录为准。',
        ))
        # Index readable food descriptions, not duplicate JSON and hash strings.
        # The original record travels in document metadata, never as a QA answer.
        # Keep canonical numbers in a string: JavaScript clients otherwise
        # serialize 52.0 as 52 and invalidate the original record fingerprint.
        metadata.update(record_json=canonical(row), content_sha256=sha256(content),
                        document_format='nutritionist_food_document_v1')
        documents.append({'document_id': f'food:{row["code"]}', 'record': row,
                          'page_content': content, 'metadata': metadata})
    return snapshot_id, documents


def build_bisheng_document_batches(documents, batch_size=100):
    """Presegmented documents for BiSheng v1.3.1 /filelib/chunks_string.

    Its implementation splits each Document at double newlines with size 1000.
    Fail before import if a record could be split from its metadata. Each batch
    becomes a readable TXT file; each food remains exactly one indexed chunk.
    """
    if type(batch_size) is not int or not 1 <= batch_size <= 100:
        raise ValueError('Document batch size must be between 1 and 100')
    batches = []
    for start in range(0, len(documents), batch_size):
        filename = f'食品营养-{start // batch_size + 1:03d}.txt'
        entries = []
        for document in documents[start:start + batch_size]:
            text = document['page_content']
            if len(text) > 1000 or '\n\n' in text:
                raise ValueError('Food document would be split by BiSheng; shorten display fields first')
            entries.append({'page_content': text,
                            'metadata': dict(document['metadata'], source=filename)})
        batches.append({'filename': filename, 'documents': entries})
    return batches


def validate_output_directory(output):
    """Fail closed for tracked/trackable paths inside any enclosing checkout."""
    output = Path(output).expanduser().resolve()
    repository = next((parent for parent in (output, *output.parents)
                       if (parent / '.git').exists()), None)
    if repository is None:
        return output
    try:
        tracked = subprocess.run(
            ['git', '-C', str(repository), 'ls-files', '-z', '--', str(output)],
            capture_output=True, check=True,
        )
        if tracked.stdout:
            raise ValueError('Refusing to write generated food data over tracked files')
        for filename in FILENAMES:
            result = subprocess.run(
                ['git', '-C', str(repository), 'check-ignore', '--quiet', '--no-index', '--', str(output / filename)],
                capture_output=True,
            )
            if result.returncode != 0:
                raise ValueError('Generated food data must be written to a Git-ignored directory or outside a checkout')
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError('Cannot verify that generated food data is excluded from Git') from exc
    return output


def build_qa_records(documents):
    """BiSheng QA import: one unambiguous question and JSON answer per food.

    The full name and preparation always remain in the question; aliases are
    never emitted as independent questions, since the platform deduplicates QA
    questions and different foods may share an alias.
    """
    records = []
    questions = set()
    for document in documents:
        row = document['record']
        question = ' '.join((
            f'食物名称：{row["name"]}；制作/生熟状态：{row["preparation"] or "未知（原数据未填写）"}；'
            f'常用别名：{"、".join(row["aliases"]) or "无"}'
        ).split())
        if question in questions:
            raise ValueError('Duplicate QA question; food identities must not be lost during import')
        questions.add(question)
        answer = canonical({'record': row,
                            'snapshot_id': document['metadata']['snapshot_id'],
                            'record_sha256': document['metadata']['record_sha256']})
        records.append({'question': question, 'answer': answer})
    return records


def _write_text(path, content):
    # A snapshot replaces complete files; reruns never append duplicate records.
    # Named temporary files default to owner-only permissions on Unix.
    handle = tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                         dir=path.parent, prefix=f'.{path.name}.', delete=False)
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_export(rows, output):
    """Write deterministic TXT, document/QA JSONL and a manifest, without DB writes."""
    output = validate_output_directory(output)
    snapshot_id, documents = build_documents(rows)
    contents = {
        'food_documents.jsonl': ''.join(canonical(document) + '\n' for document in documents),
        'food_catalog.txt': RECORD_SEPARATOR.join(document['page_content'] for document in documents),
        'qa_records.jsonl': ''.join(canonical(record) + '\n' for record in build_qa_records(documents)),
        'bisheng_document_batches.json': canonical(build_bisheng_document_batches(documents)) + '\n',
    }
    manifest = {
        'schema_version': 1, 'origin': 'nutritionist_db', 'snapshot_id': snapshot_id,
        'total': len(documents), 'basis_g': 100, 'nutrition_units': UNITS,
        'qa_total': len(documents), 'qa_answer_format': 'json(record,snapshot_id,record_sha256)',
        'document_format': 'nutritionist_food_document_v1',
        'document_files': (len(documents) + 99) // 100,
        'fields': list(FIELDS), 'split_separator': RECORD_SEPARATOR,
        'min_chunk_characters': min(len(document['page_content']) for document in documents),
        'max_chunk_characters': max(len(document['page_content']) for document in documents),
        'files_sha256': {filename: sha256(content) for filename, content in contents.items()},
        'items': [{'code': document['record']['code'],
                   'document_id': document['document_id'],
                   'record_sha256': document['metadata']['record_sha256']} for document in documents],
    }
    contents['manifest.json'] = json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    for filename, content in contents.items():
        _write_text(output / filename, content)
    return manifest


async def export(output):
    # Validate before opening the database. Import lazily so document formatting
    # and manifest validation can also be used without a configured database.
    validate_output_directory(output)
    from .food_catalog import catalog_rows
    return write_export(await catalog_rows(), output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True,
                        help='Explicit private output directory; inside Git it must be ignored')
    args = parser.parse_args(argv)
    try:
        manifest = asyncio.run(export(args.output))
    except ValueError as exc:
        parser.error(str(exc))
    print(canonical({key: manifest[key] for key in ('snapshot_id', 'total', 'basis_g', 'files_sha256')}))


if __name__ == '__main__':
    main()
