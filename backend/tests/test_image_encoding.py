import asyncio
import io
import threading
from types import SimpleNamespace

from fastapi import UploadFile
import pytest

from app import main


def test_cancelled_upload_waits_for_encoder_and_removes_only_its_file(tmp_path,monkeypatch):
    started,release=threading.Event(),threading.Event()
    sentinel=tmp_path/'existing.jpg';sentinel.write_bytes(b'existing private image')
    def encode(raw,path):
        started.set()
        assert release.wait(5)
        path.write_bytes(raw)
    monkeypatch.setattr(main,'settings',SimpleNamespace(app_media_dir=tmp_path))
    monkeypatch.setattr(main,'IMAGE_SEM',asyncio.Semaphore(1))
    monkeypatch.setattr(main,'encode_uploaded_image',encode)
    async def scenario():
        file=UploadFile(filename='meal.jpg',file=io.BytesIO(b'test private image'))
        task=asyncio.create_task(main.upload_image(file=file,user='test-user'))
        assert await asyncio.to_thread(started.wait,5)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):await task
        assert main.IMAGE_SEM._value==1
    asyncio.run(scenario())
    assert list(tmp_path.iterdir())==[sentinel]
    assert sentinel.read_bytes()==b'existing private image'
