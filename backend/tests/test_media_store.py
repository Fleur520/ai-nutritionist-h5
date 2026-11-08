import asyncio
import ssl

from app import main
from app.db import mysql_tls
from app.media_store import initialize_media
from test_bisheng_api_integration import recognition_api


def test_database_photos_survive_local_disk_loss_and_remain_private(recognition_api, monkeypatch):
    fixture = recognition_api
    monkeypatch.setattr(fixture.settings, 'app_image_storage', 'database')
    monkeypatch.setattr(fixture.settings, 'app_nginx_accel', True)
    asyncio.run(initialize_media(fixture.settings))
    image_id = fixture.upload()
    original = fixture.client.get('/api/images/' + image_id)
    assert original.status_code == 200
    assert original.headers['content-type'] == 'image/jpeg'
    assert original.headers['cache-control'] == 'private, no-store'
    assert 'x-accel-redirect' not in original.headers
    path = fixture.settings.app_media_dir / (image_id + '.jpg')
    path.unlink()
    after_loss = fixture.client.get('/api/images/' + image_id)
    assert after_loss.content == original.content
    seen = []
    async def recognize(path, mime, timings):
        seen.append(path.read_bytes())
        return []
    monkeypatch.setattr(main, 'recognize_workflow_image', recognize)
    result = fixture.client.post('/api/meals/recognize', json={'image_id': image_id})
    assert result.status_code == 200, result.text
    assert seen == [original.content]
    assert path.read_bytes() == original.content
    fixture.register()
    assert fixture.client.get('/api/images/' + image_id).status_code == 404
    assert fixture.client.post('/api/meals/recognize', json={'image_id': image_id}).status_code == 404


def test_hosted_mysql_tls_verifies_certificate_and_hostname(recognition_api):
    settings = recognition_api.settings.model_copy()
    assert mysql_tls(settings) is None
    settings.mysql_ssl_enabled = True
    context = mysql_tls(settings)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
