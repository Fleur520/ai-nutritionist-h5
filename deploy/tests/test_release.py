import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from release import ReleaseManager
from controller import extract_source
import io
import tarfile


class FakeManager(ReleaseManager):
    def __init__(self,root,fail=None):
        with patch('release.subprocess.run',return_value=subprocess.CompletedProcess([],0)):
            super().__init__(root,model_check=False)
        self.calls=[];self.fail=fail
    def run(self,command,**kwargs):
        self.calls.append(command)
        if self.fail=='build' and 'build' in command:raise RuntimeError('Build failed')
        return ''
    def verify(self,release):
        self.calls.append(['verify',release['revision']])
        if self.fail=='acceptance' and release['revision']=='a'*40:raise RuntimeError('Wrong version')
        return {'status':'passed','revision':release['revision']}


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'app';self.root.mkdir();(self.root/'.env').write_text('DEMO_MODE=true\n')
        self.source=Path(self.temp.name)/'source';self.source.mkdir()
        (self.source/'docker-compose.yml').write_text('services: {}\n')
        self.previous={'revision':'b'*40,'directory':str(self.root/'previous'),
            'api_image':'local/api:previous','web_image':'local/web:previous','legacy':False}
        Path(self.previous['directory']).mkdir()
    def manager(self,fail=None):
        manager=FakeManager(self.root,fail);manager.write_json(manager.state_dir/'active.json',self.previous);return manager
    def test_success_activates_only_after_acceptance(self):
        manager=self.manager();result=manager.deploy(self.source,'a'*40)
        self.assertEqual(result['status'],'deployed');self.assertEqual(manager.current()['revision'],'a'*40)
        self.assertIn(['verify','a'*40],manager.calls)
        self.assertTrue((manager.state_dir/'previous.json').exists())
    def test_acceptance_failure_restores_and_checks_previous_release(self):
        manager=self.manager('acceptance')
        with self.assertRaises(RuntimeError):manager.deploy(self.source,'a'*40)
        self.assertEqual(manager.current(),self.previous)
        self.assertIn(['verify','b'*40],manager.calls)
        ups=[x for x in manager.calls if 'up' in x]
        self.assertEqual(len(ups),2)
        report=json.loads((manager.state_dir/'reports'/('a'*40+'.json')).read_text())
        self.assertEqual(report['status'],'rolled-back')
    def test_build_failure_does_not_restart_running_release(self):
        manager=self.manager('build')
        with self.assertRaises(RuntimeError):manager.deploy(self.source,'a'*40)
        self.assertFalse(any('up' in x for x in manager.calls))
        self.assertEqual(manager.current(),self.previous)
    def test_repeat_current_revision_is_a_noop(self):
        manager=self.manager();result=manager.deploy(self.source,'b'*40)
        self.assertEqual(result['status'],'already-deployed');self.assertEqual(manager.calls,[])
    def test_archive_cannot_write_outside_release_directory(self):
        stream=io.BytesIO()
        with tarfile.open(fileobj=stream,mode='w:gz') as archive:
            item=tarfile.TarInfo('repo/../../outside');item.size=4;archive.addfile(item,io.BytesIO(b'test'))
        with self.assertRaises(ValueError):extract_source(stream.getvalue(),self.root/'download')
        self.assertFalse((self.root.parent/'outside').exists())


if __name__=='__main__':unittest.main()
