import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bisheng_food_fastpath import PREPARE_IMAGE_CODE, enable_image_reference
from bisheng_food_workflow import build_workflow
from test_bisheng_food_workflow import code_main


class FastImageWorkflowTests(unittest.TestCase):
    def load(self, raw=b'image', *, width=1536, format='JPEG'):
        self.saved = []
        self.requests = []
        response = io.BytesIO(raw)
        def download(url, timeout):
            self.requests.append((url, timeout))
            return response
        class Picture:
            height = 700
            def __enter__(picture):
                picture.width, picture.format = width, format
                return picture
            def __exit__(picture, *args):
                pass
            def verify(picture):
                pass
        def save(data, directory, filename):
            self.saved.append((data, directory, filename))
            return '/managed/cache/' + filename
        self.addCleanup(patch.stopall)
        patch.dict(sys.modules, {'bisheng.cache.utils': SimpleNamespace(save_download_file=save)}).start()
        patch('urllib.request.build_opener', return_value=SimpleNamespace(open=download)).start()
        patch('PIL.Image.open', return_value=Picture()).start()
        return code_main(PREPARE_IMAGE_CODE)

    def test_reference_uses_bounded_storage_download_and_native_cache(self):
        prepare = self.load()
        result = prepare(None, 'http://storage:9000/tmp-dir/unique.jpg', 0, 'http://storage:9000', '/tmp-dir/')
        self.assertEqual(self.requests, [('http://storage:9000/tmp-dir/unique.jpg', 8)])
        self.assertEqual(self.saved, [(b'image', 'bisheng', 'unique.jpg')])
        self.assertEqual(result['files'], ['/managed/cache/unique.jpg'])

    def test_reference_rejects_origin_escape_paths_and_non_images_before_download(self):
        prepare = self.load()
        for url in ('http://evil/tmp-dir/a.jpg', 'http://storage:9000@evil/tmp-dir/a.jpg',
                    'http://storage:9000/other/a.jpg', 'http://storage:9000/tmp-dir/../a.jpg',
                    'http://storage:9000/tmp-dir/%2e%2e/a.jpg', 'http://storage:9000/tmp-dir/%252e%252e/a.jpg',
                    'http://storage:9000/tmp-dir/a.jpg?redirect=evil', 'http://storage:9000/tmp-dir/a.jpg#x',
                    'http://storage:9000/tmp-dir/a.pdf', 'http://storage:9000/tmp-dir/a%00.jpg'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                prepare(None, url, 0, 'http://storage:9000', '/tmp-dir/')
        self.assertFalse(self.requests)

    def test_rejects_oversize_and_unsupported_decoded_images(self):
        for options in ({'raw': b'x' * (5 * 1024 * 1024 + 1)}, {'width': 24000}, {'format': 'GIF'}):
            with self.subTest(options=list(options)):
                prepare = self.load(**options)
                with self.assertRaises(ValueError):
                    prepare([], 'http://storage:9000/tmp-dir/a.jpg', 0, 'http://storage:9000', '/tmp-dir/')
                self.assertFalse(self.saved)

    def test_native_file_branch_keeps_platform_upload_and_does_not_download_again(self):
        prepare = self.load()
        with patch('os.path.isfile', return_value=True):
            result = prepare(['/native/image.jpg'], '', 0, 'http://storage:9000', '/tmp-dir/')
        self.assertEqual(result['files'], ['/native/image.jpg'])
        self.assertFalse(self.requests)

    def test_graph_keeps_real_document_retrieval_and_native_vision(self):
        body = enable_image_reference(build_workflow(7, 11, 12, snapshot_id='a' * 64), 'http://storage:9000')
        nodes = {n['id']: n for n in body['data']['nodes']}
        self.assertEqual(len(nodes), 11)
        get = lambda key: {p['key']: p['value'] for group in nodes[key]['data']['group_params'] for p in group['params']}
        self.assertEqual(get('llm_vision')['model_id'], 11)
        self.assertEqual(get('llm_vision')['image_prompt'], ['prepare_image.files'])
        self.assertIn('similarity_search_with_score_by_vector', get('code_retrieve')['code'])
        self.assertNotIn('skip_image_text_extraction', json.dumps(body))
        self.assertEqual([f['type'] for f in get('input_meal')['form_input']], ['file', 'text'])
        self.assertTrue(all(not f['required'] for f in get('input_meal')['form_input']))
        for node in nodes.values():
            if node['data']['type'] == 'code':
                code_main(get(node['id'])['code']) if node['id'] not in {'code_retrieve', 'prepare_image'} else None

    def test_configuration_requires_single_storage_origin_and_scoped_directory(self):
        for origin, prefix in [('http://a/x', '/tmp/'), ('http://u:p@a', '/tmp/'), ('http://a', '/'),
                               ('http://a', '/tmp/../'), ('http://a?x=y', '/tmp/')]:
            with self.assertRaises(ValueError):
                enable_image_reference(build_workflow(7, 11, 12, snapshot_id='a' * 64), origin, prefix)
