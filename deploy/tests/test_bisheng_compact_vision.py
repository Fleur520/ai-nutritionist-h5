import base64
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bisheng_compact_vision import COMPACT_VISION_CODE, enable_compact_vision
from bisheng_food_workflow import build_workflow
from test_bisheng_food_workflow import code_main


class CompactVisionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.photo = Path(self.folder.name) / 'photo.jpg'
        Image.new('RGB', (12, 8), 'green').save(self.photo)
        self.requests, self.quotas, self.statuses, self.loads = [], [], [], []
        self.content = '{"items":[]}'
        self.body = json.dumps({'choices': [{'message': {'content': self.content}}]}).encode()
        self.error = None
        self.handlers = []
        self.native = type('ChatOpenAI', (), {})()
        self.native.openai_api_base = 'http://model.test/v1'
        self.native.openai_api_key = SimpleNamespace(get_secret_value=lambda: 'private-test-key')
        self.native.default_headers = {'X-Test': 'value'}
        self.native.openai_proxy = None
        self.native.default_query = None
        self.native._default_params = {'model': 'configured-model', 'temperature': .1, 'max_tokens': 1024,
                                       'extra_body': {'chat_template_kwargs': {'enable_thinking': False}}}
        self.model = SimpleNamespace(llm=self.native, _update_model_status=lambda *args: self.statuses.append(args))

    def load(self):
        def model(**kwargs):
            self.loads.append(kwargs)
            return self.model
        def opener(*handlers):
            self.handlers = handlers
            def send(request, timeout):
                self.requests.append((request, timeout))
                if self.error:
                    raise self.error
                return io.BytesIO(self.body)
            return SimpleNamespace(open=send)
        modules = {'bisheng.api.services.llm': SimpleNamespace(LLMService=SimpleNamespace(get_bisheng_llm=model)),
                   'bisheng.interface.utils': SimpleNamespace(bisheng_model_limit_check=lambda model: self.quotas.append(model))}
        self.addCleanup(patch.stopall)
        patch.dict(sys.modules, modules).start()
        function = code_main(COMPACT_VISION_CODE)
        patch('urllib.request.build_opener', side_effect=opener).start()
        return function

    def run_call(self):
        return self.load()([str(self.photo)], 44, 'system', 'user')

    def test_same_model_configuration_and_quota_with_bounded_nonstream_request(self):
        result = self.run_call()
        self.assertEqual(result, {'output': self.content})
        self.assertEqual(self.loads, [{'model_id': 44, 'temperature': .1, 'params': {'stream': False}, 'cache': False}])
        self.assertEqual(self.quotas, [self.model])
        self.assertEqual(self.statuses, [(0,)])
        request, timeout = self.requests[0]
        body = json.loads(request.data)
        self.assertEqual(request.full_url, 'http://model.test/v1/chat/completions')
        self.assertEqual(timeout, 12)
        self.assertFalse(body['stream'])
        self.assertEqual(body['model'], 'configured-model')
        self.assertEqual(body['max_tokens'], 1024)
        self.assertEqual(body['chat_template_kwargs'], {'enable_thinking': False})
        self.assertNotIn('extra_body', body)
        image = body['messages'][1]['content'][1]['image_url']['url']
        self.assertEqual(base64.b64decode(image.split(',', 1)[1]), self.photo.read_bytes())
        self.assertNotIn('private-test-key', json.dumps(result))

    def test_network_errors_expose_no_private_response_or_key(self):
        self.error = TimeoutError('private-test-key sensitive-response')
        with self.assertRaisesRegex(ValueError, '^视觉模型调用失败$') as caught:
            self.run_call()
        self.assertTrue(caught.exception.__suppress_context__)
        self.assertEqual(self.statuses, [(1, 'TimeoutError')])

    def test_bad_or_oversized_model_responses_fail_without_returning_provider_body(self):
        for body in (b'not-json private-test-key', b'{}', b'x' * (2 * 1024 * 1024 + 1),
                     json.dumps({'choices': [{'message': {'content': ''}}]}).encode()):
            with self.subTest(size=len(body)):
                self.body = body
                with self.assertRaisesRegex(ValueError, '^视觉模型调用失败$'):
                    self.run_call()

    def test_only_explicit_openai_configuration_is_supported(self):
        self.native = type('OtherClient', (), {})()
        self.model.llm = self.native
        with self.assertRaises(ValueError):
            self.run_call()
        self.assertFalse(self.requests)
        self.assertFalse(self.quotas)

    def test_configured_proxy_or_query_requires_original_native_path(self):
        for field in ('openai_proxy', 'default_query'):
            with self.subTest(field=field):
                setattr(self.native, field, 'configured')
                with self.assertRaises(ValueError):
                    self.run_call()
                setattr(self.native, field, None)
        self.assertFalse(self.requests)

    def test_invalid_endpoint_or_header_rejected_before_request(self):
        for url in ('file:///private', 'http://user:password@model.test/v1', 'http://model.test/v1?key=x'):
            self.native.openai_api_base = url
            with self.assertRaises(ValueError):
                self.run_call()
        self.native.openai_api_base = 'http://model.test/v1'
        self.native.default_headers = {'X-Test': 'unsafe\r\nheader'}
        with self.assertRaises(ValueError):
            self.run_call()
        self.assertFalse(self.requests)

    def test_redirect_is_forbidden(self):
        self.run_call()
        with self.assertRaisesRegex(ValueError, '重定向'):
            self.handlers[1].redirect_request(None)

    def test_image_validation_precedes_model_loading(self):
        self.photo.write_bytes(b'x' * (5 * 1024 * 1024 + 1))
        with self.assertRaises(ValueError):
            self.run_call()
        self.assertFalse(self.loads)
        self.assertFalse(self.requests)

    def test_generator_keeps_only_paths_prompts_and_model_id_in_node_inputs(self):
        body = enable_compact_vision(build_workflow(7, 44, 12, snapshot_id='a' * 64))
        node = next(n for n in body['data']['nodes'] if n['id'] == 'llm_vision')
        params = {p['key']: p['value'] for group in node['data']['group_params'] for p in group['params']}
        inputs = {row['key']: row['value'] for row in params['code_input']}
        self.assertEqual(node['data']['type'], 'code')
        self.assertEqual(inputs['model_id'], 44)
        self.assertEqual(inputs['files'], 'input_meal.meal_image_files')
        self.assertNotIn('private-test-key', json.dumps(params['code_input']))
        self.assertEqual(params['code_output'], [{'key': 'output', 'type': 'str'}])
