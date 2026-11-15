import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
from app import main, triage
from app.auth import current_user


def test_multiturn_mcp_selection_and_emergency(monkeypatch):
    decisions = iter([
        {'urgent': False, 'question': '咳嗽持续多久了？', 'department_codes': [], 'reason': ''},
        {'urgent': False, 'question': '', 'department_codes': ['respiratory'], 'reason': '因有咳嗽症状。'},
        {'urgent': True, 'question': '', 'department_codes': [], 'reason': ''},
        {'urgent': False, 'question': '', 'department_codes': ['imaginary'], 'reason': ''},
    ])
    seen = []
    class FakeModel:
        def __init__(self, **kwargs): pass
        async def ainvoke(self, messages):
            seen.append(messages)
            return SimpleNamespace(content=json.dumps(next(decisions), ensure_ascii=False))
    monkeypatch.setattr(triage, 'ChatOpenAI', FakeModel)
    monkeypatch.setattr(triage, 'get_settings', lambda: SimpleNamespace(
        vllm_chat_completions_url='http://example.invalid/v1/chat/completions',
        vllm_model='test', vllm_api_key='', vllm_api_style='vllm'))
    main.app.dependency_overrides[current_user] = lambda: 'test-user'
    try:
        with TestClient(main.app) as client:
            first = [{'role': 'user', 'content': '我咳嗽'}]
            response = client.post('/api/triage', json={'messages': first})
            assert response.status_code == 200
            question = response.json()['reply']
            assert '多久' in question
            history = first + [{'role': 'assistant', 'content': question}, {'role': 'user', 'content': '三天'}]
            response = client.post('/api/triage', json={'messages': history})
            assert response.status_code == 200
            assert '呼吸内科' in response.json()['reply']
            assert '三天' in seen[1][1].content
            response = client.post('/api/triage', json={'messages': [{'role': 'user', 'content': '严重呼吸困难'}]})
            assert response.status_code == 200 and '120' in response.json()['reply']
            response = client.post('/api/triage', json={'messages': first})
            assert response.status_code == 503
            assert client.post('/api/triage', json={'messages': [{'role': 'assistant', 'content': 'x'}]}).status_code == 422
    finally:
        main.app.dependency_overrides.pop(current_user, None)


def test_triage_requires_authentication():
    with TestClient(main.app) as client:
        assert client.post('/api/triage', json={'messages': [{'role': 'user', 'content': '头疼'}]}).status_code == 401
