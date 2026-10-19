"""Real BiSheng protocol shapes with MockTransport, never a live service."""
import asyncio
import json
from types import SimpleNamespace
import uuid

from fastapi import HTTPException
import httpx
import pytest

from app import bisheng_recognition as adapter


WORKFLOW_ID = 'a041c42b-6ab5-48d7-9fd0-25fa692537ab'
SESSION = 'fixture_async_task_id'
SNAPSHOT = 'a' * 64
RECORD_HASH = 'b' * 64
UPLOADED = '/tmp/workflow/photo.jpg'
_ASYNC_CLIENT = httpx.AsyncClient


def result_payload(**changes):
    value = {
        'schema_version': 1, 'snapshot_id': SNAPSHOT,
        'items': [{
            'name': '蒸紫薯', 'estimated_grams': 123.5, 'preparation': '蒸熟', 'food_code': 'purple',
            'candidates': [{'code': 'purple', 'name': '蒸紫薯', 'preparation': '蒸熟', 'basis_g': 100,
                            'kcal': 999999, 'record_sha256': RECORD_HASH, 'snapshot_id': SNAPSHOT}],
            'retrieval_evidence': [{'food_code': 'purple', 'knowledge_id': 7, 'source': 'bisheng_qa',
                                    'snapshot_id': SNAPSHOT, 'record_sha256': RECORD_HASH,
                                    'raw_answer': '{"record":{"code":"purple"}}'}],
            'kcal': 999999, 'api_key': 'must not propagate',
        }],
    }
    value.update(changes)
    return value


def input_event(**changes):
    value = {
        'event': 'input', 'status': 'end', 'node_id': 'input_meal', 'message_id': '123',
        'input_schema': {'input_type': 'form_input', 'value': [
            {'key': 'meal_image', 'type': 'file', 'required': True},
        ]},
    }
    value.update(changes)
    return value


def output_events(payload=None):
    return [
        {'event': 'output_msg', 'status': 'end', 'output_schema': {'message': json.dumps(payload or result_payload(), ensure_ascii=False)}},
        {'event': 'close', 'status': 'end', 'output_schema': None},
    ]


def response(events, **changes):
    value = {'status_code': 200, 'data': {'session_id': SESSION, 'events': events}}
    value.update(changes)
    return value


@pytest.fixture
def configured(monkeypatch, tmp_path):
    settings = SimpleNamespace(
        bisheng_recognition_base_url='http://bisheng.test:7860',
        bisheng_recognition_workflow_id=WORKFLOW_ID,
        bisheng_recognition_api_key='', bisheng_recognition_input_field='user_input',
        bisheng_recognition_image_key='meal_image', bisheng_recognition_timeout=240,
    )
    photo = tmp_path / 'photo.jpg'
    photo.write_bytes(b'private-test-image-content')
    monkeypatch.setattr(adapter, 'get_settings', lambda: settings)
    return settings, photo


def install_transport(monkeypatch, rounds=None, upload=None, *, stop_error=False, invoke_error=None):
    calls, invocations = [], []
    rounds = [response([input_event()]), response(output_events())] if rounds is None else rounds
    async def handler(request):
        content = await request.aread()
        call = {'url': str(request.url), 'headers': dict(request.headers), 'content': content}
        calls.append(call)
        if '/api/v1/upload/' in request.url.path:
            return httpx.Response(200, json=upload if upload is not None else {'status_code': 200, 'data': {'file_path': UPLOADED}})
        call['json'] = json.loads(content)
        if request.url.path.endswith('/stop'):
            if stop_error:
                raise httpx.ConnectError('cleanup unavailable', request=request)
            return httpx.Response(200, json={'status_code': 200, 'data': None})
        invocations.append(call)
        if invoke_error and len(invocations) == 2:
            raise invoke_error(request)
        value = rounds[len(invocations) - 1]
        return value if isinstance(value, httpx.Response) else httpx.Response(200, json=value)
    monkeypatch.setattr(adapter.httpx, 'AsyncClient', lambda **kwargs: _ASYNC_CLIENT(transport=httpx.MockTransport(handler), **kwargs))
    return calls, invocations


def run(photo):
    return asyncio.run(adapter.recognize_workflow_image(photo, 'image/jpeg'))


def assert_failure(photo, status=502):
    with pytest.raises(HTTPException) as error:
        run(photo)
    assert error.value.status_code == status
    assert 'must not propagate' not in str(error.value.detail)


def test_upload_nested_user_input_and_same_session_roundtrip(configured, monkeypatch):
    _, photo = configured
    calls, invocations = install_transport(monkeypatch)
    items = run(photo)
    assert len(calls) == 3 and len(invocations) == 2
    assert calls[0]['url'].endswith('/api/v1/upload/' + uuid.UUID(WORKFLOW_ID).hex)
    assert 'multipart/form-data;' in calls[0]['headers']['content-type']
    assert b'name="file"; filename="photo.jpg"' in calls[0]['content']
    assert b'private-test-image-content' in calls[0]['content']
    assert 'authorization' not in calls[0]['headers']
    assert invocations[0]['json'] == {'workflow_id': WORKFLOW_ID, 'stream': False}
    assert invocations[1]['json'] == {
        'workflow_id': WORKFLOW_ID, 'stream': False, 'session_id': SESSION, 'message_id': 123,
        'user_input': {'input_meal': {'meal_image': [UPLOADED]}},
    }
    assert items[0]['name'] == '蒸紫薯' and items[0]['estimated_grams'] == 123.5
    assert items[0]['snapshot_id'] == SNAPSHOT
    assert items[0]['retrieval_evidence'][0]['raw_answer'] == '{"record":{"code":"purple"}}'
    assert 'kcal' not in items[0] and 'kcal' not in items[0]['candidates'][0]
    assert 'api_key' not in items[0]


def test_phase_timings_include_transport_and_validation_without_private_data(configured, monkeypatch):
    _, photo = configured
    install_transport(monkeypatch)
    timings = {}
    items = asyncio.run(adapter.recognize_workflow_image(photo, 'image/jpeg', timings))
    assert items and set(timings) == {'upload', 'invoke_0', 'invoke_1', 'validation'}
    assert all(type(value) is int and value >= 0 for value in timings.values())


def test_reference_capability_skips_file_parsing_only_when_explicitly_advertised(configured, monkeypatch):
    _, photo = configured
    event = input_event()
    event['input_schema']['value'] = [
        {'key': 'meal_image', 'type': 'file', 'required': False},
        {'key': 'meal_image_ref', 'type': 'text', 'required': False},
    ]
    _, invocations = install_transport(monkeypatch, rounds=[response([event]), response(output_events())])
    run(photo)
    assert invocations[1]['json']['user_input'] == {'input_meal': {'meal_image': [], 'meal_image_ref': UPLOADED}}


def test_node_timings_are_bounded_allowlisted_and_do_not_enter_food_results(configured, monkeypatch):
    _, photo = configured
    payload = result_payload(timings_ms={'image': 12, 'vision': 1234.5, 'matching': True,
                                       'retrieval': -1, 'pipeline_total': 3600001,
                                       'private_path': '/private/photo.jpg'})
    install_transport(monkeypatch, rounds=[response([input_event()]), response(output_events(payload))])
    timings = {}
    items = asyncio.run(adapter.recognize_workflow_image(photo, 'image/jpeg', timings))
    assert {key: value for key, value in timings.items() if key.startswith('node_')} == {'node_image': 12, 'node_vision': 1234}
    assert 'timings_ms' not in items[0]


def test_document_provenance_survives_adapter_without_document_body(configured, monkeypatch):
    _, photo = configured
    payload = result_payload()
    entry = payload['items'][0]['retrieval_evidence'][0]
    entry.pop('raw_answer')
    entry.update(source='bisheng_document', file_id=123, chunk_index=5,
                 document_name='食品营养-001.txt', content_sha256='c' * 64,
                 raw_record='must not propagate', page_content='must not propagate')
    install_transport(monkeypatch, rounds=[response([input_event()]), response(output_events(payload))])
    evidence = run(photo)[0]['retrieval_evidence'][0]
    assert evidence['source'] == 'bisheng_document'
    assert (evidence['file_id'], evidence['chunk_index']) == (123, 5)
    assert evidence['document_name'] == '食品营养-001.txt'
    assert evidence['content_sha256'] == 'c' * 64
    assert 'raw_record' not in evidence and 'page_content' not in evidence


@pytest.mark.parametrize('changes', [dict(file_id=True), dict(file_id=0), dict(chunk_index=-1),
                                  dict(content_sha256='bad'), dict(document_name='x' * 201)])
def test_document_evidence_invalid_location_or_digest_fails_closed(configured, monkeypatch, changes):
    _, photo = configured
    payload = result_payload()
    payload['items'][0]['retrieval_evidence'][0].update(changes)
    install_transport(monkeypatch, rounds=[response([input_event()]), response(output_events(payload))])
    assert_failure(photo)


def test_input_alias_config_and_optional_gateway_key(configured, monkeypatch):
    settings, photo = configured
    settings.bisheng_recognition_input_field = 'input'
    settings.bisheng_recognition_api_key = 'fixture-token'
    calls, invocations = install_transport(monkeypatch)
    run(photo)
    assert all(call['headers']['authorization'] == 'Bearer fixture-token' for call in calls)
    assert 'input' in invocations[1]['json'] and 'user_input' not in invocations[1]['json']


@pytest.mark.parametrize('location', ['http://minio:9000/tmp-dir/photo.jpg', 'https://minio.test/photo.jpg?signature=fixture', '/tmp/workflow/photo.jpg'])
def test_upload_location_is_passed_back_without_downloading_or_rewriting(configured, monkeypatch, location):
    _, photo = configured
    calls, invocations = install_transport(monkeypatch, upload={'code': 0, 'data': {'file_path': location}})
    run(photo)
    assert invocations[1]['json']['user_input']['input_meal']['meal_image'] == [location]
    assert len(calls) == 3


@pytest.mark.parametrize('location', ['relative/photo.jpg', '//minio/photo.jpg', 'file:///etc/passwd', 'ftp://minio/photo.jpg', 'http://user:password@minio/photo.jpg', None])
def test_invalid_upload_location_stops_before_starting_workflow(configured, monkeypatch, location):
    _, photo = configured
    calls, invocations = install_transport(monkeypatch, upload={'code': 0, 'data': {'file_path': location}})
    assert_failure(photo)
    assert len(calls) == 1 and not invocations


@pytest.mark.parametrize('field,value', [
    ('bisheng_recognition_base_url', ''), ('bisheng_recognition_base_url', 'file:///tmp'),
    ('bisheng_recognition_workflow_id', 'bad-uuid'), ('bisheng_recognition_input_field', 'query'),
    ('bisheng_recognition_image_key', ''), ('bisheng_recognition_timeout', 0),
])
def test_missing_configuration_is_503_without_a_request(configured, monkeypatch, field, value):
    settings, photo = configured
    setattr(settings, field, value)
    calls, _ = install_transport(monkeypatch)
    assert_failure(photo, 503)
    assert not calls


@pytest.mark.parametrize('wrap', [lambda value: value, lambda value: '```json\n' + value + '\n```', lambda value: '```\n' + value + '\n```'])
def test_complete_json_and_markdown_fences(configured, monkeypatch, wrap):
    _, photo = configured
    events = output_events()
    events[0]['output_schema']['message'] = wrap(events[0]['output_schema']['message'])
    install_transport(monkeypatch, [response([input_event()]), response(events)])
    assert run(photo)[0]['food_code'] == 'purple'


def test_empty_items_is_a_valid_no_food_result(configured, monkeypatch):
    _, photo = configured
    install_transport(monkeypatch, [response([input_event()]), response(output_events(result_payload(items=[])))])
    assert run(photo) == []


@pytest.mark.parametrize('weight', [True, '100', 0, 3001, 10 ** 1000, float('nan'), float('inf')])
def test_invalid_weights_are_controlled_errors_and_stop_session(configured, monkeypatch, weight):
    _, photo = configured
    value = result_payload()
    value['items'][0]['estimated_grams'] = weight
    calls, _ = install_transport(monkeypatch, [response([input_event()]), response(output_events(value))])
    assert_failure(photo)
    assert calls[-1]['url'].endswith('/stop')
    assert calls[-1]['json'] == {'workflow_id': WORKFLOW_ID, 'session_id': SESSION}


@pytest.mark.parametrize('change', [
    lambda value: value.update(schema_version=True),
    lambda value: value.update(snapshot_id='invented-snapshot'),
    lambda value: value.update(items=value['items'] * 9),
    lambda value: value['items'][0].update(name='x' * 101),
    lambda value: value['items'][0].update(candidates='not-a-list'),
    lambda value: value['items'][0]['candidates'][0].update(code='other-code', food_code='purple'),
    lambda value: value['items'][0]['candidates'][0].update(basis_g=1),
    lambda value: value['items'][0].update(retrieval_evidence=[{'food_code': 'purple', 'raw_answer': 'x' * 100001}]),
])
def test_malformed_structured_result_is_rejected(configured, monkeypatch, change):
    _, photo = configured
    value = result_payload()
    change(value)
    calls, _ = install_transport(monkeypatch, [response([input_event()]), response(output_events(value))])
    assert_failure(photo)
    assert calls[-1]['url'].endswith('/stop')


@pytest.mark.parametrize('events', [
    [], [{'event': 'error', 'output_schema': {'message': 'secret upstream error'}}],
    [{'event': 'close', 'status': 'end', 'output_schema': {'message': {'error': 'failed'}}}],
    output_events()[:1],
    [{'event': 'output_msg', 'status': 'stream', 'output_schema': {'message': 'partial'}}, {'event': 'close'}],
    [{'event': 'close', 'status': 'failed'}],
    [{'event': 'made_up_event'}],
])
def test_missing_terminal_or_error_events_are_not_success(configured, monkeypatch, events):
    _, photo = configured
    calls, _ = install_transport(monkeypatch, [response([input_event()]), response(events)])
    assert_failure(photo)
    assert calls[-1]['url'].endswith('/stop')


def test_success_before_image_input_is_rejected(configured, monkeypatch):
    _, photo = configured
    calls, _ = install_transport(monkeypatch, [response(output_events())])
    assert_failure(photo)
    assert calls[-1]['url'].endswith('/stop')


@pytest.mark.parametrize('event', [
    input_event(node_id=None), input_event(message_id='not-a-number'), input_event(status='stream'),
    input_event(input_schema={'input_type': 'dialog_input', 'value': []}),
    input_event(input_schema={'input_type': 'form_input', 'value': [{'key': 'other_image', 'type': 'file'}]}),
])
def test_unexpected_input_schema_is_rejected(configured, monkeypatch, event):
    _, photo = configured
    calls, invocations = install_transport(monkeypatch, [response([event])])
    assert_failure(photo)
    assert len(invocations) == 1 and calls[-1]['url'].endswith('/stop')


def test_repeated_input_does_not_loop(configured, monkeypatch):
    _, photo = configured
    calls, invocations = install_transport(monkeypatch, [response([input_event()]), response([input_event()])])
    assert_failure(photo)
    assert len(invocations) == 2 and calls[-1]['url'].endswith('/stop')


@pytest.mark.parametrize('http_status', [401, 429, 500])
def test_http_errors_are_controlled_without_fallback(configured, monkeypatch, http_status):
    _, photo = configured
    calls, _ = install_transport(monkeypatch, [response([input_event()]), httpx.Response(http_status, text='upstream detail')])
    assert_failure(photo)
    assert calls[-1]['url'].endswith('/stop')
    assert all('model' not in call['url'] for call in calls)


def test_timeout_and_failed_cleanup_preserve_original_error(configured, monkeypatch):
    _, photo = configured
    calls, _ = install_transport(monkeypatch, stop_error=True, invoke_error=lambda request: httpx.ReadTimeout('fixture timeout', request=request))
    assert_failure(photo)
    assert calls[-1]['url'].endswith('/stop')


@pytest.mark.parametrize('envelope', [
    {'data': {'session_id': SESSION, 'events': []}},
    {'status_code': 200, 'code': 500, 'data': {'session_id': SESSION, 'events': []}},
    {'status_code': True, 'data': {}}, {'code': 0, 'data': []},
])
def test_bad_envelope_is_rejected(configured, monkeypatch, envelope):
    _, photo = configured
    install_transport(monkeypatch, [envelope])
    assert_failure(photo)


def test_session_identity_cannot_change(configured, monkeypatch):
    _, photo = configured
    second = response(output_events())
    second['data']['session_id'] = 'different_session'
    calls, _ = install_transport(monkeypatch, [response([input_event()]), second])
    assert_failure(photo)
    assert calls[-1]['json']['session_id'] == SESSION


def test_oversized_response_is_bounded(configured, monkeypatch):
    _, photo = configured
    calls, _ = install_transport(monkeypatch, [response([input_event()]), httpx.Response(200, content=b'x' * (adapter._MAX_RESPONSE_BYTES + 1))])
    assert_failure(photo)
    assert calls[-1]['url'].endswith('/stop')


def test_total_timeout_also_bounds_a_slow_transport(configured, monkeypatch):
    settings, photo = configured
    settings.bisheng_recognition_timeout = .02
    calls = []
    async def handler(request):
        calls.append(request.url.path)
        if '/upload/' in request.url.path:
            return httpx.Response(200, json={'code': 0, 'data': {'file_path': UPLOADED}})
        payload = json.loads(await request.aread())
        if request.url.path.endswith('/stop'):
            return httpx.Response(200, json={'code': 0, 'data': None})
        if payload.get('session_id'):
            await asyncio.sleep(1)
        return httpx.Response(200, json=response([input_event()]))
    monkeypatch.setattr(adapter.httpx, 'AsyncClient', lambda **kwargs: _ASYNC_CLIENT(transport=httpx.MockTransport(handler), **kwargs))
    assert_failure(photo)
    assert calls[-1].endswith('/stop')


def test_caller_cancellation_stops_session_and_is_not_reported_as_502(configured, monkeypatch):
    _, photo = configured
    calls = []
    ready = asyncio.Event()
    async def handler(request):
        calls.append(request.url.path)
        if '/upload/' in request.url.path:
            return httpx.Response(200, json={'code': 0, 'data': {'file_path': UPLOADED}})
        payload = json.loads(await request.aread())
        if request.url.path.endswith('/stop'):
            return httpx.Response(200, json={'code': 0, 'data': None})
        if payload.get('session_id'):
            ready.set()
            await asyncio.sleep(10)
        return httpx.Response(200, json=response([input_event()]))
    monkeypatch.setattr(adapter.httpx, 'AsyncClient', lambda **kwargs: _ASYNC_CLIENT(transport=httpx.MockTransport(handler), **kwargs))
    async def scenario():
        task = asyncio.create_task(adapter.recognize_workflow_image(photo, 'image/jpeg'))
        await asyncio.wait_for(ready.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(scenario())
    assert calls[-1].endswith('/stop')


@pytest.mark.parametrize('message', ['', 'not JSON', '```json\n{}', 'leading words ' + json.dumps(result_payload())])
def test_invalid_output_text_is_not_salvaged_as_a_success(configured, monkeypatch, message):
    _, photo = configured
    events = output_events()
    events[0]['output_schema']['message'] = message
    calls, _ = install_transport(monkeypatch, [response([input_event()]), response(events)])
    assert_failure(photo)
    assert calls[-1]['url'].endswith('/stop')
