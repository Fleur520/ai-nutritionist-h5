import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from app import ai


def model(monkeypatch, frames):
    requests = []
    client = httpx.AsyncClient

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, text=''.join('data: ' + frame + '\n\n' for frame in frames))

    monkeypatch.setattr(ai.httpx, 'AsyncClient', lambda **kwargs: client(transport=httpx.MockTransport(handle), **kwargs))
    monkeypatch.setattr(ai, 'get_settings', lambda: SimpleNamespace(
        demo_mode=False, vllm_chat_completions_url='https://model.test/v1/chat/completions',
        vllm_model='qwen3.7-flash', vllm_api_key='test-key', vllm_max_tokens=1536,
        vllm_api_style='bailian'))
    return requests


def frame(content='', finish=None):
    return json.dumps({'choices': [{'delta': {'content': content}, 'finish_reason': finish}]})


def collect():
    async def run():
        return ''.join([part async for part in ai.chat_chunks('早餐怎么吃？', [], {})])
    return asyncio.run(run())


def test_bailian_chat_disables_thinking_and_streams_complete_reply(monkeypatch):
    requests = model(monkeypatch, [frame('均衡早餐'), frame(finish='stop'), json.dumps({'choices': [], 'usage': {}}), '[DONE]'])
    assert collect() == '均衡早餐'
    assert requests[0]['model'] == 'qwen3.7-flash'
    assert requests[0]['enable_thinking'] is False
    assert requests[0]['stream'] is True
    assert 'chat_template_kwargs' not in requests[0]


@pytest.mark.parametrize('frames', [
    [frame('部分建议'), frame(finish='length'), '[DONE]'],
    [frame('部分建议'), '[DONE]'],
    [frame('部分建议')],
    [json.dumps({'error': {'message': 'unavailable'}})],
])
def test_incomplete_upstream_replies_are_not_reported_as_success(monkeypatch, frames):
    model(monkeypatch, frames)
    with pytest.raises(ValueError):
        collect()
