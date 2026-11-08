from app import main
from test_bisheng_api_integration import recognition_api


def test_login_alias_preserves_identity_and_requires_the_existing_password(recognition_api, monkeypatch):
    client = recognition_api.client
    original = client.get('/api/auth/me').json()
    monkeypatch.setattr(main, 'settings', recognition_api.settings.model_copy(update={
        'app_login_alias': 'andy', 'app_login_alias_email': original['email'],
    }))
    client.cookies.clear()
    assert client.post('/api/auth/login', json={'email': 'andy', 'password': 'wrong_password'}).status_code == 401
    assert client.get('/api/auth/me').status_code == 401
    response = client.post('/api/auth/login', json={'email': ' ANDY ', 'password': 'isolated_test_password_123'})
    assert response.status_code == 200
    assert client.get('/api/auth/me').json() == original
    client.cookies.clear()
    assert client.post('/api/auth/login', json={'email': original['email'], 'password': 'isolated_test_password_123'}).status_code == 200
    assert client.post('/api/auth/register', json={'email': 'andy', 'password': 'isolated_test_password_123'}).status_code == 422


def test_login_alias_is_disabled_unless_configured(recognition_api):
    response = recognition_api.client.post('/api/auth/login', json={'email': 'andy', 'password': 'isolated_test_password_123'})
    assert response.status_code == 401

