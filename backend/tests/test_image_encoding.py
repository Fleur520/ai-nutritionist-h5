import asyncio
import io
import threading
from types import SimpleNamespace

from fastapi import UploadFile
import pytest
from PIL import Image

from app import main


@pytest.mark.parametrize('size,expected',[((4096,1848),(1536,693)),((900,1600),(864,1536)),((500,400),(500,400))])
def test_upload_bounds_visual_pixels_preserves_aspect_and_never_upscales(tmp_path,monkeypatch,size,expected):
    raw=io.BytesIO()
    Image.new('RGB',size,'orange').save(raw,format='PNG')
    monkeypatch.setattr(main,'settings',SimpleNamespace(app_image_max_edge=1536))
    target=tmp_path/'processed.jpg'
    main.encode_uploaded_image(raw.getvalue(),target)
    with Image.open(target) as photo:
        assert photo.format=='JPEG' and photo.size==expected and photo.mode=='RGB'


def test_upload_rotation_happens_before_size_limit(tmp_path,monkeypatch):
    raw=io.BytesIO()
    photo=Image.new('RGB',(1600,900),'orange')
    exif=Image.Exif();exif[274]=6
    photo.save(raw,format='JPEG',exif=exif)
    monkeypatch.setattr(main,'settings',SimpleNamespace(app_image_max_edge=1536))
    target=tmp_path/'rotated.jpg'
    main.encode_uploaded_image(raw.getvalue(),target)
    with Image.open(target) as decoded:
        assert decoded.size==(864,1536)
        assert decoded.getexif().get(274,1)==1


@pytest.mark.parametrize('cancel_count',[1,3])
@pytest.mark.parametrize('encoder_fails',[False,True])
def test_cancelled_upload_waits_for_encoder_and_removes_only_its_file(tmp_path,monkeypatch,cancel_count,encoder_fails):
    started,release=threading.Event(),threading.Event()
    sentinel=tmp_path/'existing.jpg';sentinel.write_bytes(b'existing private image')
    def encode(raw,path):
        started.set()
        assert release.wait(5)
        path.write_bytes(raw)
        if encoder_fails: raise ValueError('invalid image')
    monkeypatch.setattr(main,'settings',SimpleNamespace(app_media_dir=tmp_path))
    monkeypatch.setattr(main,'IMAGE_SEM',asyncio.Semaphore(1))
    monkeypatch.setattr(main,'encode_uploaded_image',encode)
    async def scenario():
        file=UploadFile(filename='meal.jpg',file=io.BytesIO(b'test private image'))
        task=asyncio.create_task(main.upload_image(file=file,user='test-user'))
        assert await asyncio.to_thread(started.wait,5)
        for _ in range(cancel_count):
            task.cancel()
            await asyncio.sleep(0)
        assert not task.done()
        assert main.IMAGE_SEM._value==0
        release.set()
        with pytest.raises(asyncio.CancelledError):await task
        assert main.IMAGE_SEM._value==1
    asyncio.run(scenario())
    assert list(tmp_path.iterdir())==[sentinel]
    assert sentinel.read_bytes()==b'existing private image'
