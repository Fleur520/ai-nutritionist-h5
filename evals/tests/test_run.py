import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from evals.run import evaluate, load_cases, main


class FakeJudge:
    def __init__(self, scores=None, error=None):
        self.scores, self.error = scores, error

    async def score(self, row):
        if self.error:
            raise self.error
        return self.scores, []


class EvaluationTests(unittest.TestCase):
    def test_invalid_and_duplicate_cases_rejected(self):
        good = {'id': 'a', 'user_input': '问', 'response': '答'}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'cases.jsonl'
            for rows in ([], [good, good], [good | {'retrieved_contexts': 'text'}], [good | {'response': ''}]):
                path.write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf-8')
                with self.assertRaises(ValueError):
                    load_cases(path)

    def test_fail_closed_on_empty_invalid_or_failed_scores(self):
        for judge in (FakeJudge({}), FakeJudge({'metric': float('nan')}), FakeJudge({'metric': 1.1}), FakeJudge({'metric': 0.69}), FakeJudge(error=RuntimeError('secret'))):
            result = asyncio.run(evaluate([{'id': 'a'}], {'test': judge}, .7, 1))
            self.assertFalse(result['passed'])
            self.assertNotIn('secret', json.dumps(result))

    def test_individual_failure_cannot_hide_in_average(self):
        result = asyncio.run(evaluate([{'id': 'a'}], {'a': FakeJudge({'m': 1}), 'b': FakeJudge({'m': .6})}, .7, 1))
        self.assertFalse(result['passed'])
        self.assertTrue(result['results'][0]['passed'])

    def test_timeout_fails_closed(self):
        class Slow:
            async def score(self, row):
                await asyncio.sleep(1)
        result = asyncio.run(evaluate([{'id': 'a'}], {'slow': Slow()}, .7, .001))
        self.assertEqual(result['results'][0]['error'], 'TimeoutError')

    def test_examples_validate_without_dependencies(self):
        path = Path(__file__).resolve().parents[1] / 'examples/nutrition.jsonl'
        self.assertEqual(main(['--dataset', str(path), '--validate-only']), 0)


if __name__ == '__main__':
    unittest.main()
