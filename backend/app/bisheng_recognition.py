"""BiSheng image upload and v1.3.1 workflow invocation without admin sessions.

Only the workflow's structured output is retained. Database matching and all
nutrition calculations remain the caller's responsibility.
"""
import asyncio
import json
import logging
import math
from pathlib import Path, PurePosixPath
import re
import time
from urllib.parse import urlsplit
import uuid

import httpx
from fastapi import HTTPException

from .config import get_settings


log = logging.getLogger(__name__)
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_ROUNDS = 3
_ERROR_MESSAGE = 'BiSheng 食物识别工作流执行失败，请重试或手动记录'
_CANDIDATE_FIELDS = ('code', 'food_code', 'name', 'preparation', 'basis_g', 'snapshot_id', 'record_sha256')
_EVIDENCE_FIELDS = ('food_code', 'knowledge_id', 'snapshot_id', 'record_sha256', 'source', 'raw_answer',
                    'file_id', 'chunk_index', 'document_name', 'content_sha256')


def _configuration():
    settings = get_settings()
    try:
        base_url = settings.bisheng_recognition_base_url.rstrip('/')
        parsed = urlsplit(base_url)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('invalid base URL')
        workflow = uuid.UUID(settings.bisheng_recognition_workflow_id)
        input_field = settings.bisheng_recognition_input_field
        image_key = settings.bisheng_recognition_image_key
        timeout = settings.bisheng_recognition_timeout
        if input_field not in {'input', 'user_input'} or not isinstance(image_key, str) or not image_key or len(image_key) > 100:
            raise ValueError('invalid input settings')
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('invalid timeout')
        key = settings.bisheng_recognition_api_key
        if not isinstance(key, str) or '\n' in key or '\r' in key:
            raise ValueError('invalid API key')
    except (AttributeError, ValueError, TypeError, OverflowError) as exc:
        raise HTTPException(503, '请配置 BiSheng 食物识别地址、工作流 ID 和图片输入字段') from exc
    return base_url, workflow, input_field, image_key, float(timeout), {'Authorization': f'Bearer {key}'} if key else {}


async def _post_json(client, url, **kwargs):
    async with client.stream('POST', url, **kwargs) as response:
        response.raise_for_status()
        body = bytearray()
        async for chunk in response.aiter_bytes():
            if len(body) + len(chunk) > _MAX_RESPONSE_BYTES:
                raise ValueError('workflow response too large')
            body.extend(chunk)
    value = json.loads(body)
    if not isinstance(value, dict):
        raise ValueError('response must be an object')
    codes = [value[field] for field in ('status_code', 'code') if field in value]
    if not codes or any(type(code) is not int or code not in {0, 200} for code in codes):
        raise ValueError('BiSheng non-success response')
    data = value.get('data')
    if not isinstance(data, dict):
        raise ValueError('response has no data object')
    return data


def _code(value, *, optional=False):
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        raise ValueError('invalid food code')
    return value


def _bounded_text(value, limit, *, empty=False):
    if not isinstance(value, str) or len(value) > limit or not empty and not value.strip():
        raise ValueError('invalid text field')
    return value


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('invalid snapshot/hash format')
    return value


def _candidate(value):
    if not isinstance(value, dict):
        raise ValueError('invalid retrieved candidate')
    food_code = _code(value.get('food_code') or value.get('code'))
    if value.get('food_code') and value.get('code') and value['food_code'] != value['code']:
        raise ValueError('candidate code identity conflict')
    result = {key: value[key] for key in _CANDIDATE_FIELDS if key in value}
    result['food_code'] = food_code
    if 'name' in result:
        _bounded_text(result['name'], 100)
    if 'preparation' in result:
        _bounded_text(result['preparation'], 32, empty=True)
    if 'basis_g' in result and (type(result['basis_g']) not in {int, float} or result['basis_g'] != 100):
        raise ValueError('candidate nutrition basis is not 100g')
    for key in ('snapshot_id', 'record_sha256', 'content_sha256'):
        if key in result:
            _hash(result[key])
    return result


def _evidence(value):
    if not isinstance(value, dict):
        raise ValueError('invalid retrieval evidence')
    result = {key: value[key] for key in _EVIDENCE_FIELDS if key in value}
    _code(result.get('food_code'))
    if 'knowledge_id' in result and not (
        type(result['knowledge_id']) is int and result['knowledge_id'] > 0
        or isinstance(result['knowledge_id'], str) and 0 < len(result['knowledge_id']) <= 100
    ):
        raise ValueError('invalid knowledge ID')
    for key in ('snapshot_id', 'record_sha256', 'content_sha256'):
        if key in result:
            _hash(result[key])
    if 'source' in result:
        _bounded_text(result['source'], 64)
    if 'raw_answer' in result:
        _bounded_text(result['raw_answer'], 100000)
    if 'document_name' in result:
        _bounded_text(result['document_name'], 200)
    for key, minimum in (('file_id', 1), ('chunk_index', 0)):
        if key in result and (type(result[key]) is not int or result[key] < minimum):
            raise ValueError('invalid document location')
    return result


def _structured_items(message):
    if isinstance(message, str):
        text = message.strip()
        if text.startswith('```'):
            match = re.fullmatch(r'```(?:json)?[ \t]*\r?\n(.*?)\r?\n?```', text, re.DOTALL | re.IGNORECASE)
            if not match:
                raise ValueError('invalid JSON fence')
            text = match.group(1).strip()
        def reject_constant(_):
            raise ValueError('non-finite JSON constant')
        value = json.loads(text, parse_constant=reject_constant)
    else:
        value = message
    if not isinstance(value, dict) or type(value.get('schema_version')) is not int or value['schema_version'] != 1:
        raise ValueError('unsupported recognition schema')
    snapshot = _hash(value.get('snapshot_id'))
    items = value.get('items')
    if not isinstance(items, list) or len(items) > 8:
        raise ValueError('invalid food item count')
    result = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('food item must be an object')
        name = _bounded_text(item.get('name'), 100).strip()
        grams = item.get('estimated_grams')
        if isinstance(grams, bool) or not isinstance(grams, (int, float)) or not 5 <= grams <= 3000 or not math.isfinite(grams):
            raise ValueError('invalid estimated food weight')
        preparation = _bounded_text(item.get('preparation', ''), 32, empty=True)
        candidates, evidence = item.get('candidates', []), item.get('retrieval_evidence', [])
        if not isinstance(candidates, list) or len(candidates) > 32 or not isinstance(evidence, list) or len(evidence) > 32:
            raise ValueError('invalid retrieval list')
        cleaned = {
            'name': name, 'estimated_grams': grams, 'preparation': preparation,
            'food_code': _code(item.get('food_code'), optional=True),
            'candidates': [_candidate(candidate) for candidate in candidates],
            'retrieval_evidence': [_evidence(entry) for entry in evidence],
            'snapshot_id': snapshot,
        }
        if 'retrieved_codes' in item:
            codes = item['retrieved_codes']
            if not isinstance(codes, list) or len(codes) > 32:
                raise ValueError('invalid retrieved codes')
            cleaned['retrieved_codes'] = list(dict.fromkeys(_code(code) for code in codes))
        result.append(cleaned)
    return result


def _image_input(event, image_key, uploaded_path):
    node_id = _bounded_text(event.get('node_id'), 100)
    schema = event.get('input_schema')
    if not isinstance(schema, dict) or schema.get('input_type') != 'form_input' or not isinstance(schema.get('value'), list):
        raise ValueError('unexpected workflow input schema')
    fields = schema['value']
    if any(not isinstance(field, dict) for field in fields):
        raise ValueError('invalid input field')
    image_fields = [field for field in fields if field.get('key') == image_key and field.get('type') == 'file']
    if len(image_fields) != 1 or any(field.get('required') and field.get('key') != image_key for field in fields):
        raise ValueError('configured image field is not the workflow input')
    return {node_id: {image_key: [uploaded_path]}}


async def _stop(client, base_url, workflow_id, session_id, headers):
    if not session_id:
        return
    try:
        async with asyncio.timeout(5):
            response = await client.post(base_url + '/api/v2/workflow/stop', headers=headers,
                                         json={'workflow_id': workflow_id, 'session_id': session_id}, timeout=5)
            response.raise_for_status()
    except (httpx.HTTPError, OSError, ValueError, TimeoutError):
        log.warning('BiSheng workflow cleanup did not finish')


async def recognize_workflow_image(path: Path, mime: str, timings: dict | None = None) -> list[dict]:
    """Upload one private photo and consume the published workflow's final output."""
    base_url, workflow, input_field, image_key, timeout, headers = _configuration()
    workflow_id, session_id = str(workflow), ''
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=min(8, timeout))) as client:
        try:
            async with asyncio.timeout(timeout):
                phase_started=time.perf_counter()
                with path.open('rb') as photo:
                    upload = await _post_json(client, base_url + '/api/v1/upload/' + workflow.hex,
                                              files={'file': (path.name, photo, mime)}, headers=headers)
                if timings is not None:
                    timings['upload']=round((time.perf_counter()-phase_started)*1000)
                uploaded_path = upload.get('file_path')
                if not isinstance(uploaded_path, str) or len(uploaded_path) > 4096 or '\x00' in uploaded_path:
                    raise ValueError('upload did not return a valid file location')
                uploaded_url = urlsplit(uploaded_path)
                local_path = PurePosixPath(uploaded_path).is_absolute() and not uploaded_path.startswith('//')
                absolute_url = uploaded_url.scheme in {'http', 'https'} and uploaded_url.hostname and not uploaded_url.username and not uploaded_url.password
                if not local_path and not absolute_url:
                    raise ValueError('upload did not return an absolute path or HTTP URL')
                payload = {'workflow_id': workflow_id, 'stream': False}
                submitted_image, seen_inputs = False, set()
                for round_index in range(_MAX_ROUNDS):
                    phase_started=time.perf_counter()
                    data = await _post_json(client, base_url + '/api/v2/workflow/invoke', json=payload, headers=headers)
                    if timings is not None:
                        timings['invoke_'+str(round_index)]=round((time.perf_counter()-phase_started)*1000)
                    returned_session = _bounded_text(data.get('session_id'), 200)
                    if session_id and session_id != returned_session:
                        raise ValueError('workflow session changed')
                    session_id = returned_session
                    events = data.get('events')
                    if not isinstance(events, list) or not events or len(events) > 200:
                        raise ValueError('missing workflow events')
                    pending, messages, closed = [], [], False
                    for event in events:
                        if not isinstance(event, dict) or closed:
                            raise ValueError('invalid workflow event sequence')
                        kind = event.get('event')
                        if kind == 'error' or event.get('status') in {'error', 'failed', 'failure', 'stopped', 'cancelled', 'canceled'}:
                            raise ValueError('workflow error event')
                        if kind == 'input':
                            if event.get('status', 'end') != 'end':
                                raise ValueError('unfinished workflow input request')
                            pending.append(event)
                        elif kind == 'output_msg':
                            if event.get('status', 'end') != 'end' or not isinstance(event.get('output_schema'), dict):
                                raise ValueError('unfinished workflow output')
                            messages.append(event['output_schema'].get('message'))
                        elif kind == 'close':
                            schema = event.get('output_schema')
                            if event.get('status', 'end') != 'end' or schema is not None and (
                                not isinstance(schema, dict) or schema.get('message') not in (None, '')
                            ):
                                raise ValueError('workflow closed with an error')
                            closed = True
                        elif kind not in {'node_run', 'guide_word', 'guide_question', 'stream_msg'}:
                            raise ValueError('unsupported workflow event')
                    if pending:
                        if closed or messages or len(pending) != 1:
                            raise ValueError('ambiguous workflow input request')
                        event = pending[0]
                        identity = (event.get('node_id'), event.get('message_id'))
                        if identity in seen_inputs:
                            raise ValueError('workflow repeated the same input')
                        seen_inputs.add(identity)
                        payload = {'workflow_id': workflow_id, 'stream': False, 'session_id': session_id,
                                   input_field: _image_input(event, image_key, uploaded_path)}
                        message_id = event.get('message_id')
                        if message_id is not None:
                            if isinstance(message_id, bool) or not re.fullmatch(r'[0-9]+', str(message_id)):
                                raise ValueError('invalid workflow message ID')
                            payload['message_id'] = int(message_id)
                        submitted_image = True
                        continue
                    if not closed or not submitted_image or len(messages) != 1:
                        raise ValueError('workflow did not finish with one image result')
                    phase_started=time.perf_counter()
                    items=_structured_items(messages[0])
                    if timings is not None:
                        timings['validation']=round((time.perf_counter()-phase_started)*1000)
                    return items
                raise ValueError('too many workflow input rounds')
        except asyncio.CancelledError:
            await _stop(client, base_url, workflow_id, session_id, headers)
            raise
        except (httpx.HTTPError, ValueError, TypeError, KeyError, OSError, TimeoutError) as exc:
            await _stop(client, base_url, workflow_id, session_id, headers)
            log.warning('BiSheng image workflow failed: %s', type(exc).__name__)
            raise HTTPException(502, _ERROR_MESSAGE) from exc
