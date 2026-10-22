import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bisheng_food_workflow import build_workflow
from bisheng_model_nutrition import enable_model_nutrition
from bisheng_code_runtime import enable_compact_vision_output, defer_code_compilation
from test_bisheng_food_workflow import code_main


def params(body, name):
    node = next(n for n in body['data']['nodes'] if n['id'] == name)
    return {p['key']: p for g in node['data']['group_params'] for p in g['params']}


class ModelNutritionTests(unittest.TestCase):
    def graph(self):
        return defer_code_compilation(enable_compact_vision_output(enable_model_nutrition(
            build_workflow(7, 44, 12, snapshot_id='a' * 64), 44)))

    def test_visual_values_survive_unmatched_finalization(self):
        body = self.graph()
        parse = code_main(params(body, 'code_foods')['code']['value'])
        item = parse('{"items":[["汤面",450,"煮熟",120,4,4,17]]}', 8)['items'][0]
        self.assertEqual(item['nutrition'], {'basis_g': 100, 'kcal': 120, 'protein': 4, 'fat': 4, 'carbs': 17})
        self.assertEqual(item['source_model'], 'bisheng:model:44')
        item.update(candidates=[], retrieval_evidence=[])
        finish = code_main(params(body, 'code_result')['code']['value'])
        result = json.loads(finish(json.dumps({'schema_version': 1, 'snapshot_id': 'a' * 64, 'items': [item]}))['result'])
        self.assertIsNone(result['items'][0]['food_code'])
        self.assertEqual(result['items'][0]['nutrition'], item['nutrition'])
        self.assertFalse(result['items'][0]['verified'])

    def test_missing_invalid_or_wrong_basis_values_do_not_become_zero(self):
        parse = code_main(params(self.graph(), 'code_foods')['code']['value'])
        for row in [['汤面', 450, '煮熟'], ['汤面', 450, '煮熟', -1, 4, 4, 17],
                    ['汤面', 450, '煮熟', 120, 100, 10, 17], ['汤面', 450, '煮熟', True, 4, 4, 17]]:
            with self.subTest(row=row), self.assertRaises(ValueError):
                parse(json.dumps({'items': [row]}), 8)
