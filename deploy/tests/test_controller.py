import json
import io
import os
from pathlib import Path
import sys
import tempfile
import tarfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import controller


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sha = 'a' * 40
        self.manager = Mock()
        self.manager.state_dir = self.root
        self.manager.current.return_value = None
        self.config = {'repository': 'Fleur520/ai-nutritionist-h5',
                       'root': str(self.root), 'base_url': 'http://127.0.0.1:18081'}

    def test_missing_workflow_keeps_running_version(self):
        missing = urllib.error.HTTPError('https://api.github.com/test', 404, 'missing', {}, None)
        with patch('controller.ReleaseManager', return_value=self.manager), patch(
            'controller.fetch', side_effect=[{'sha': self.sha}, missing]
        ):
            self.assertEqual(controller.check(self.config)['status'], 'waiting-for-ci-workflow')
        self.manager.deploy.assert_not_called()

    def test_only_successful_main_push_for_exact_commit_is_eligible(self):
        valid = {'head_sha': self.sha, 'event': 'push', 'head_branch': 'main',
                 'status': 'completed', 'conclusion': 'success', 'html_url': 'https://github.com/run/1'}
        for invalid in ({'event': 'pull_request'}, {'head_sha': 'b' * 40},
                        {'head_branch': 'feature'}, {'status': 'in_progress'}, {'conclusion': 'failure'}):
            with self.subTest(invalid=invalid), patch('controller.ReleaseManager', return_value=self.manager), patch(
                'controller.fetch', side_effect=[{'sha': self.sha}, {'workflow_runs': [{**valid, **invalid}]}]
            ):
                self.assertEqual(controller.check(self.config)['status'], 'waiting-for-successful-ci')
        self.manager.deploy.assert_not_called()

    def test_success_downloads_exact_commit_before_deploy(self):
        run = {'head_sha': self.sha, 'event': 'push', 'head_branch': 'main',
               'status': 'completed', 'conclusion': 'success', 'html_url': 'https://github.com/run/1'}
        self.manager.deploy.return_value = {'status': 'deployed'}
        with patch('controller.ReleaseManager', return_value=self.manager), patch(
            'controller.fetch', side_effect=[{'sha': self.sha}, {'workflow_runs': [run]}, b'archive']
        ) as fetch, patch('controller.extract_source') as extract:
            self.assertEqual(controller.check(self.config)['ci_run_url'], run['html_url'])
        self.assertTrue(fetch.call_args.args[0].endswith('/tarball/' + self.sha))
        extract.assert_called_once_with(b'archive', self.root / 'downloads' / self.sha)
        self.manager.deploy.assert_called_once_with(self.root / 'downloads' / self.sha, self.sha)

    def test_failed_commit_is_held_without_redeploying(self):
        (self.root / 'reports').mkdir()
        (self.root / 'reports' / (self.sha + '.json')).write_text(json.dumps({'status': 'rolled-back'}))
        with patch('controller.ReleaseManager', return_value=self.manager), patch(
            'controller.fetch', return_value={'sha': self.sha}
        ) as fetch:
            self.assertEqual(controller.check(self.config)['status'], 'failed-revision-held')
        self.assertEqual(fetch.call_count, 1)
        self.manager.deploy.assert_not_called()

    def test_extracted_source_is_readable_under_private_service_umask(self):
        stream=io.BytesIO()
        with tarfile.open(fileobj=stream,mode='w:gz') as archive:
            item=tarfile.TarInfo('repo/backend/app/__init__.py')
            item.size=4;item.mode=0o644
            archive.addfile(item,io.BytesIO(b'test'))
        previous=os.umask(0o077)
        try:
            target=self.root/'download'
            controller.extract_source(stream.getvalue(),target)
        finally:
            os.umask(previous)
        self.assertEqual((target/'backend/app/__init__.py').stat().st_mode & 0o777,0o644)
        for folder in (target,target/'backend',target/'backend/app'):
            self.assertEqual(folder.stat().st_mode & 0o777,0o755)


if __name__ == '__main__':
    unittest.main()
