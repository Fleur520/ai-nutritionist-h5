"""Regression coverage for Qwen reasoning consuming the vision output budget."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from app import ai


def setup_model(monkeypatch, tmp_path, body):
    requests = []
    original_client = httpx.AsyncClient

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=body)

    monkeypatch.setattr(ai.httpx, 'AsyncClient', lambda **kwargs: original_client(
        transport=httpx.MockTransport(handle), **kwargs))
    monkeypatch.setattr(ai, 'get_settings', lambda: SimpleNamespace(
        demo_mode=False, vllm_vision_url='',
        vllm_chat_completions_url='http://model.test/v1/chat/completions',
        vllm_vision_model='', vllm_model='Qwen3.8-27B',
        vllm_vision_api_key='', vllm_api_key='test-key',
        vllm_vision_max_tokens=1536, vllm_vision_enable_thinking=False,
    ))
    photo = tmp_path / 'photo.jpg'
    photo.write_bytes(b'test-image-bytes')
    return photo, requests


def test_vision_disables_thinking_and_parses_foods(monkeypatch, tmp_path):
    photo, requests = setup_model(monkeypatch, tmp_path, {
        'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({
            'items': [{'name': '米饭', 'estimated_grams': 150}, {'name': '紫薯', 'estimated_grams': 120}]
        })}}]
    })
    items = asyncio.run(ai.recognize_image(photo, 'image/jpeg'))
    assert [x['name'] for x in items] == ['米饭', '紫薯']
    assert items[0]['estimated_grams'] == 150
    assert requests[0]['chat_template_kwargs'] == {'enable_thinking': False}
    assert requests[0]['max_tokens'] == 1536
    assert requests[0]['response_format'] == {'type': 'json_object'}


@pytest.mark.parametrize('content', [None, '{"items":[]}', '{"items":['])
def test_truncated_vision_output_is_not_accepted(monkeypatch, tmp_path, content):
    photo, _ = setup_model(monkeypatch, tmp_path, {
        'choices': [{'finish_reason': 'length', 'message': {'content': content, 'reasoning': 'thinking'}}]
    })
    with pytest.raises(HTTPException) as error:
        asyncio.run(ai.recognize_image(photo, 'image/jpeg'))
    assert error.value.status_code == 502
    assert '未完整返回' in error.value.detail


@pytest.mark.parametrize('content', [None, '', '  '])
def test_empty_vision_content_is_a_controlled_error(monkeypatch, tmp_path, content):
    photo, _ = setup_model(monkeypatch, tmp_path, {
        'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]
    })
    with pytest.raises(HTTPException) as error:
        asyncio.run(ai.recognize_image(photo, 'image/jpeg'))
    assert error.value.status_code == 502
    assert '未返回有效识别结果' in error.value.detail


def test_empty_choices_is_a_controlled_error(monkeypatch, tmp_path):
    photo, _ = setup_model(monkeypatch, tmp_path, {'choices': []})
    with pytest.raises(HTTPException) as error:
        asyncio.run(ai.recognize_image(photo, 'image/jpeg'))
    assert error.value.status_code == 502
