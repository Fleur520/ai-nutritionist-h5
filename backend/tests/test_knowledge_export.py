import copy
import hashlib
import json
import shutil
import subprocess

import pytest

from app import knowledge_export as knowledge


def foods():
    return [
        {'code': 'test_cooked', 'name': '测试薯（蒸熟）', 'kcal': 90, 'protein': 1.1,
         'fat': 0.2, 'carbs': 21.0, 'category': '虚构测试分类', 'preparation': '蒸熟',
         'aliases': ['蒸测试薯', '熟测试薯'], 'source_type': 'ai_estimate',
         'source_model': 'fictional-model', 'batch_id': 'fictional-batch', 'basis_g': 100,
         'verified': False},
        {'code': 'test_legacy', 'name': '测试食品', 'kcal': 52.0, 'protein': 0.3,
         'fat': 0.2, 'carbs': 13.8, 'category': '原有食品', 'preparation': '',
         'aliases': [], 'source_type': 'demo', 'source_model': '', 'batch_id': '',
         'basis_g': 100, 'verified': False},
    ]


def test_hashes_are_stable_across_row_and_mapping_order():
    rows = foods()
    snapshot, documents = knowledge.build_documents(rows)
    reordered = [dict(reversed(list(row.items()))) for row in reversed(rows)]
    assert knowledge.build_documents(reordered) == (snapshot, documents)
    assert snapshot == hashlib.sha256(knowledge.canonical(rows).encode('utf-8')).hexdigest()
    changed = copy.deepcopy(rows)
    changed[0]['kcal'] = 91
    new_snapshot, new_documents = knowledge.build_documents(changed)
    assert new_snapshot != snapshot
    assert new_documents[0]['metadata']['record_sha256'] != documents[0]['metadata']['record_sha256']
    assert new_documents[1]['metadata']['record_sha256'] == documents[1]['metadata']['record_sha256']


def test_record_metadata_and_body_preserve_provenance_and_original_fields():
    rows = foods()
    snapshot, documents = knowledge.build_documents(rows)
    for row, document in zip(rows, documents):
        assert document['record'] == row
        assert document['metadata']['food_code'] == row['code']
        assert document['metadata']['snapshot_id'] == snapshot
        for field in ('preparation', 'source_type', 'source_model', 'batch_id', 'basis_g', 'verified'):
            assert document['metadata'][field] == row[field]
        assert json.loads(document['metadata']['record_json']) == row
        assert document['metadata']['record_json'] == knowledge.canonical(row)
        assert document['metadata']['content_sha256'] == knowledge.sha256(document['page_content'])
        assert knowledge.canonical(row) not in document['page_content']
        assert '每100克可食部分' in document['page_content']
        assert '未经核验' in document['page_content']
    assert '未知（原数据未填写）' in documents[1]['page_content']
    assert rows == foods()  # The export never mutates source rows.


def test_document_import_batches_keep_one_food_per_chunk_and_human_readable_files():
    _, documents = knowledge.build_documents(foods())
    batches = knowledge.build_bisheng_document_batches(documents, batch_size=1)
    assert len(batches) == 2
    for batch, document in zip(batches, documents):
        entry, = batch['documents']
        assert entry['metadata']['source'] == batch['filename']
        assert json.loads(entry['metadata']['record_json']) == document['record']
        assert entry['metadata']['document_format'] == 'nutritionist_food_document_v1'
        assert entry['page_content'] == document['page_content']
        assert len(entry['page_content']) <= 1000
        assert '\n\n' not in entry['page_content']
        assert '原始记录 JSON' not in entry['page_content']


def test_document_import_rejects_platform_split_risk_before_any_writes(tmp_path):
    rows = foods()
    rows[0]['aliases'] = ['x' * 1100]
    with pytest.raises(ValueError, match='would be split'):
        knowledge.write_export(rows, tmp_path / 'not-created')
    assert not (tmp_path / 'not-created').exists()


def test_extra_fields_cannot_export_user_data_or_secrets():
    rows = foods()
    clean = knowledge.build_documents(rows)
    rows[0].update(email='never-export@example.invalid', password_hash='private-hash',
                   image_path='/private/meal.jpg', meals=[{'grams': 12}], api_key='private-key')
    assert knowledge.build_documents(rows) == clean
    serialized = knowledge.canonical(clean)
    for private in ('never-export', 'private-hash', '/private/meal.jpg', 'private-key', 'image_path'):
        assert private not in serialized


def test_qa_answers_are_json_preserving_record_and_retrieval_evidence():
    rows = foods()
    # QA questions must stay on one line without modifying the original record.
    rows[0]['aliases'][0] = '蒸测试薯\n特殊叫法'
    snapshot, documents = knowledge.build_documents(rows)
    records = knowledge.build_qa_records(documents)
    for row, document, record in zip(rows, documents, records):
        assert set(record) == {'question', 'answer'}
        assert row['name'] in record['question']
        assert (row['preparation'] or '未知（原数据未填写）') in record['question']
        assert '\n' not in record['question']
        answer = json.loads(record['answer'])
        assert answer == {'record': row, 'snapshot_id': snapshot,
                          'record_sha256': document['metadata']['record_sha256']}
        assert isinstance(answer['record']['verified'], bool)
        assert 'food_code' not in answer['record']  # The canonical DB key is code.
    assert rows[0]['aliases'][0] == '蒸测试薯\n特殊叫法'


def test_duplicate_qa_questions_are_rejected_before_platform_can_deduplicate():
    row = foods()[0]
    other = copy.deepcopy(row)
    other['code'] = 'another_code'
    _, documents = knowledge.build_documents([row, other])
    with pytest.raises(ValueError, match='Duplicate QA question'):
        knowledge.build_qa_records(documents)


def test_repeat_export_replaces_files_without_duplicate_documents(tmp_path):
    output = tmp_path / 'snapshot'
    first = knowledge.write_export(foods(), output)
    contents = {name: (output / name).read_bytes() for name in knowledge.FILENAMES}
    assert knowledge.write_export(list(reversed(foods())), output) == first
    assert {name: (output / name).read_bytes() for name in knowledge.FILENAMES} == contents
    lines = (output / 'food_documents.jsonl').read_text(encoding='utf-8').splitlines()
    assert len(lines) == len({json.loads(line)['document_id'] for line in lines}) == 2
    chunks = (output / 'food_catalog.txt').read_text(encoding='utf-8').split(knowledge.RECORD_SEPARATOR)
    assert len(chunks) == 2
    assert all(chunk.count('数据库唯一食品代码 food_code：') == 1 for chunk in chunks)
    qa_lines = (output / 'qa_records.jsonl').read_text(encoding='utf-8').splitlines()
    assert len(qa_lines) == first['qa_total'] == 2
    assert {json.loads(json.loads(line)['answer'])['record']['code'] for line in qa_lines} == {'test_cooked', 'test_legacy'}
    assert first == json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
    for name, digest in first['files_sha256'].items():
        assert hashlib.sha256(contents[name]).hexdigest() == digest
    assert sorted(path.name for path in output.iterdir()) == sorted(knowledge.FILENAMES)


def test_duplicate_codes_fail_before_writing_any_output(tmp_path):
    rows = foods()
    rows[1]['code'] = rows[0]['code']
    with pytest.raises(ValueError, match='Duplicate food code'):
        knowledge.write_export(rows, tmp_path / 'not-created')
    assert not (tmp_path / 'not-created').exists()


@pytest.mark.parametrize(('field', 'value'), [
    ('basis_g', 1), ('basis_g', True), ('verified', 0), ('verified', True),
    ('kcal', float('nan')), ('protein', float('inf')), ('fat', True), ('carbs', -1),
    ('aliases', 'incorrect-list'), ('aliases', [12]), ('preparation', None),
    ('name', ''), ('code', ''), ('name', 'bad<<<NUTRITIONIST_FOOD_RECORD_END>>>text'),
])
def test_invalid_rows_cannot_silently_change_units_or_verification(field, value):
    rows = foods()
    rows[0][field] = value
    with pytest.raises(ValueError):
        knowledge.build_documents(rows)


def test_missing_fields_and_empty_catalog_are_rejected():
    rows = foods()
    del rows[0]['source_model']
    with pytest.raises(ValueError, match='Missing required'):
        knowledge.build_documents(rows)
    with pytest.raises(ValueError, match='non-empty'):
        knowledge.build_documents([])


def test_output_must_be_explicit_before_database_is_opened():
    with pytest.raises(SystemExit) as exc:
        knowledge.main([])
    assert exc.value.code == 2


def make_checkout(tmp_path):
    if not shutil.which('git'):
        pytest.skip('Git is required to exercise ignored-output validation')
    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    subprocess.run(['git', 'init', '--quiet', str(checkout)], check=True)
    (checkout / '.gitignore').write_text('.private/\n', encoding='utf-8')
    return checkout


def test_git_trackable_output_is_refused_and_ignored_output_allowed(tmp_path):
    checkout = make_checkout(tmp_path)
    with pytest.raises(ValueError, match='Git-ignored'):
        knowledge.write_export(foods(), checkout / 'src' / 'generated')
    assert not (checkout / 'src').exists()
    ignored = checkout / '.private' / 'knowledge'
    assert knowledge.write_export(foods(), ignored)['total'] == 2


def test_tracked_output_is_refused_even_if_it_becomes_ignored(tmp_path):
    checkout = make_checkout(tmp_path)
    output = checkout / '.private'
    output.mkdir()
    target = output / 'food_catalog.txt'
    target.write_text('preserve existing tracked file', encoding='utf-8')
    subprocess.run(['git', '-C', str(checkout), 'add', '--force', str(target)], check=True)
    with pytest.raises(ValueError, match='tracked files'):
        knowledge.write_export(foods(), output)
    assert target.read_text(encoding='utf-8') == 'preserve existing tracked file'


def test_missing_git_fails_closed_in_checkout(tmp_path, monkeypatch):
    checkout = tmp_path / 'checkout'
    (checkout / '.git').mkdir(parents=True)

    def unavailable(*args, **kwargs):
        raise FileNotFoundError('git not installed')

    monkeypatch.setattr(knowledge.subprocess, 'run', unavailable)
    with pytest.raises(ValueError, match='Cannot verify'):
        knowledge.validate_output_directory(checkout / '.private')


def test_cli_catalog_reader_uses_only_catalog_rows(tmp_path, monkeypatch, capsys):
    from app import food_catalog
    calls = []

    async def read_foods():
        calls.append('catalog_rows')
        return foods()

    monkeypatch.setattr(food_catalog, 'catalog_rows', read_foods)
    knowledge.main(['--output', str(tmp_path / 'private')])
    summary = json.loads(capsys.readouterr().out)
    assert calls == ['catalog_rows']
    assert summary['total'] == 2
    assert len(summary['snapshot_id']) == 64
    assert set(summary) == {'snapshot_id', 'total', 'basis_g', 'files_sha256'}
