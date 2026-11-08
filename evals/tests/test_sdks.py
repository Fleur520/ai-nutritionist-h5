"""Real SDK metric contracts with deterministic judge replies; no model traffic."""
import asyncio
import os
import unittest
from unittest.mock import patch

from evals.run import DeepEvalJudge, RagasJudge, disable_telemetry


@unittest.skipUnless(os.environ.get('RUN_EVAL_SDK_TESTS') == '1', 'optional SDK environment required')
class SDKContractTests(unittest.TestCase):
    config = dict(model='local-test-judge', base_url='http://localhost:9999/v1', api_key='EMPTY')
    case = dict(id='test', user_input='What is in the record?', response='Test record.',
                reference='Test record.', retrieved_contexts=['Test record.'])

    def setUp(self):
        disable_telemetry()

    def test_ragas_real_metrics(self):
        async def run():
            judge = RagasJudge(self.config)
            async def generate(prompt, response_model, **kwargs):
                data = {
                    'StatementGeneratorOutput': {'statements': ['Test record.']},
                    'NLIStatementOutput': {'statements': [{'statement': 'Test record.', 'reason': 'Supported', 'verdict': 1}]},
                    'ContextRecallOutput': {'classifications': [{'statement': 'Test record.', 'reason': 'Supported', 'attributed': 1}]},
                }
                return response_model.model_validate(data[response_model.__name__])
            try:
                with patch.object(judge.faithfulness.llm, 'agenerate', side_effect=generate):
                    scores, skipped = await judge.score(self.case)
                self.assertEqual(scores, {'faithfulness': 1, 'context_recall': 1})
                self.assertEqual(skipped, [])
                scores, skipped = await judge.score(self.case | {'retrieved_contexts': []})
                self.assertEqual(scores, {})
                self.assertEqual(len(skipped), 2)
            finally:
                await judge.close()
        asyncio.run(run())

    def test_deepeval_real_metrics(self):
        async def run():
            judge = DeepEvalJudge(self.config)
            async def generate(prompt, schema=None):
                data = {'Statements': {'statements': ['Test record.']},
                        'Truths': {'truths': ['Test record.']},
                        'Claims': {'claims': ['Test record.']},
                        'Verdicts': {'verdicts': [{'verdict': 'yes'}]}}
                return schema.model_validate(data[schema.__name__])
            try:
                with patch.object(judge.model, 'a_generate', side_effect=generate):
                    scores, skipped = await judge.score(self.case)
                    self.assertEqual(scores, {'answer_relevancy': 1, 'faithfulness': 1})
                    self.assertEqual(skipped, [])
                    scores, skipped = await judge.score(self.case | {'retrieved_contexts': []})
                    self.assertEqual(scores, {'answer_relevancy': 1})
                    self.assertEqual(len(skipped), 1)
            finally:
                await judge.close()
        asyncio.run(run())
