import ast
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bisheng_code_runtime import defer_code_compilation, enable_compact_vision_output
from bisheng_compact_vision import enable_compact_vision
from bisheng_food_fastpath import enable_image_reference
from bisheng_food_workflow import build_workflow, main
from test_bisheng_food_workflow import answer, code_main, matches


def params(body, node_id):
    node = next(n for n in body['data']['nodes'] if n['id'] == node_id)
    return {p['key']: p for group in node['data']['group_params'] for p in group['params']}


def fresh():
    return enable_compact_vision(enable_image_reference(
        build_workflow(7, 44, 12, snapshot_id='a' * 64, batch_document_search=True), 'http://storage:9000'))


class CodeRuntimeTests(unittest.TestCase):
    def test_compact_tuple_keeps_name_grams_preparation_and_native_time_outputs(self):
        body = defer_code_compilation(enable_compact_vision_output(fresh()))
        function = code_main(params(body, 'code_foods')['code']['value'])
        result = function('{"items":[["白米饭",150,"煮熟"]]}', 8, 0)
        self.assertEqual(result['items'], [{'name': '白米饭', 'estimated_grams': 150, 'preparation': '煮熟'}])
        self.assertIsInstance(result['vision_ms'], int)
        self.assertEqual(function('```json\n{"items":[]}\n```', 8, 0)['items'], [])

    def test_short_format_reuses_name_weight_count_and_preparation_validation(self):
        function = code_main(params(enable_compact_vision_output(fresh()), 'code_foods')['code']['value'])
        invalid = [None, {}, {'items': {}}, {'items': [[]]}, {'items': [['rice', 1]]},
                   {'items': [{'name': 'rice', 'estimated_grams': 100}]},
                   {'items': [['', 100, '煮熟']]}, {'items': [['rice', True, '煮熟']]},
                   {'items': [['rice', 4, '煮熟']]}, {'items': [['rice', 3001, '煮熟']]},
                   {'items': [['rice', float('nan'), '煮熟']]}, {'items': [['rice', 100, 99]]},
                   {'items': [['rice', 100, '煮熟']] * 9}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                function(json.dumps(value), 8, 0)

    def test_deferred_code_initialization_does_not_import_server_dependencies(self):
        body = defer_code_compilation(fresh())
        with patch('test_bisheng_food_workflow.importlib.import_module', side_effect=AssertionError('Early import')):
            code_main(params(body, 'llm_vision')['code']['value'])
            code_main(params(body, 'code_retrieve')['code']['value'])

    def test_real_evidence_hashes_matching_and_compact_repr_survive_deferred_execution(self):
        body = defer_code_compilation(enable_compact_vision_output(fresh()))
        collect = code_main(params(body, 'code_evidence')['code']['value'])
        evidence = collect([{'name': '白米饭', 'estimated_grams': 100}], [matches(answer())], 7, 'a' * 64)
        original = json.loads(evidence['evidence_json'])
        self.assertEqual(original['items'][0]['candidates'][0]['food_code'], 'rice')
        self.assertEqual(original['snapshot_id'], 'a' * 64)
        self.assertLess(len(repr(evidence['evidence_json'])), 100)
        finish = code_main(params(body, 'code_result')['code']['value'])
        result = finish(evidence['evidence_json'], 0, 1, 2, 3, 4, 5, '{}')['result']
        value = json.loads(result)
        self.assertEqual(value['items'][0]['food_code'], 'rice')
        self.assertEqual(value['items'][0]['retrieval_evidence'][0]['record_sha256'],
                         json.loads(answer())['record_sha256'])
        self.assertEqual(value['timings_ms']['vision'], 3)
        self.assertLess(len(repr(result)), 100)

    def test_deferred_namespace_does_not_retain_request_values_between_calls(self):
        body = fresh()
        p = params(body, 'code_retrieve')
        p['code_input']['value'] = [{'key': 'request_value', 'type': 'input', 'value': ''}]
        p['code']['value'] = ('history = []\ndef main(request_value):\n'
                             '    history.append(request_value)\n    return list(history)\n' + '# authored logic\n' * 100)
        function = code_main(params(defer_code_compilation(body), 'code_retrieve')['code']['value'])
        self.assertEqual(function('first-photo'), ['first-photo'])
        self.assertEqual(function('second-photo'), ['second-photo'])

    def test_graph_io_and_small_nodes_unchanged_while_initial_ast_is_bounded(self):
        body = fresh()
        before = copy.deepcopy(body)
        defer_code_compilation(body)
        self.assertEqual(before['data']['edges'], body['data']['edges'])
        self.assertEqual(params(before, 'clock_start'), params(body, 'clock_start'))
        for n in body['data']['nodes']:
            if n['data']['type'] != 'code':
                continue
            old, new = params(before, n['id']), params(body, n['id'])
            self.assertEqual(old['code_input'], new['code_input'])
            self.assertEqual(old['code_output'], new['code_output'])
            if len(old['code']['value']) >= 1500:
                self.assertLess(len(list(ast.walk(ast.parse(new['code']['value'])))), 80)

    def test_schema_drift_and_invalid_argument_names_fail_generation(self):
        body = fresh()
        prompt = next(v for v in params(body, 'llm_vision')['code_input']['value'] if v['key'] == 'system_prompt')
        prompt['value'] = 'changed schema'
        with self.assertRaises(ValueError):
            enable_compact_vision_output(body)
        for invalid in ('a, unsafe()', 'namespace', 'class'):
            body = fresh()
            params(body, 'code_retrieve')['code_input']['value'][0]['key'] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                defer_code_compilation(body)

    def test_default_generator_keeps_original_native_schema(self):
        body = build_workflow(7, 44, 12, snapshot_id='a' * 64)
        self.assertIn('"estimated_grams":150', params(body, 'llm_vision')['system_prompt']['value'])
        self.assertNotIn('namespace = {}', params(body, 'code_foods')['code']['value'])

    def test_cli_exports_both_opt_ins_and_preserves_native_model_option(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'workflow.json'
            main(['--knowledge-id', '7', '--vision-model-id', '44', '--text-model-id', '12',
                  '--snapshot-id', 'a' * 64, '--compact-vision-output', '--defer-code-compilation',
                  '--output', str(output)])
            body = json.loads(output.read_text(encoding='utf-8'))
            self.assertIn('[["菜名",150,"蒸熟"]]', params(body, 'llm_vision')['system_prompt']['value'])
            function = code_main(params(body, 'code_foods')['code']['value'])
            self.assertEqual(function('{"items":[["白米饭",100,"煮熟"]]}', 8)['items'][0]['name'], '白米饭')
