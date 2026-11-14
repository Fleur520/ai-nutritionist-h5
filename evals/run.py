"""Evaluate captured text answers using Ragas and DeepEval, without DB access."""
import argparse
import asyncio
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit


def load_cases(path):
    cases, ids = [], set()
    for line_number, line in enumerate(Path(path).read_text(encoding='utf-8-sig').splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError('expected an object')
            for field in ('id', 'user_input', 'response'):
                if not isinstance(row.get(field), str) or not row[field].strip():
                    raise ValueError(f'{field} must be a nonempty string')
            if row['id'] in ids:
                raise ValueError('duplicate id')
            contexts = row.get('retrieved_contexts', [])
            if not isinstance(contexts, list) or any(not isinstance(x, str) or not x.strip() for x in contexts):
                raise ValueError('retrieved_contexts must be a list of nonempty strings')
            if 'reference' in row and (not isinstance(row['reference'], str) or not row['reference'].strip()):
                raise ValueError('reference must be a nonempty string')
            ids.add(row['id'])
            cases.append({k: row[k] for k in ('id', 'user_input', 'response', 'reference') if k in row} | {'retrieved_contexts': contexts})
        except (ValueError, TypeError) as exc:
            raise ValueError(f'invalid dataset line {line_number}: {exc}') from None
    if not cases:
        raise ValueError('dataset is empty')
    return cases


def judge_config():
    model = os.environ.get('EVAL_JUDGE_MODEL', '').strip()
    base_url = os.environ.get('EVAL_JUDGE_BASE_URL', '').strip().rstrip('/')
    url = urlsplit(base_url)
    if not model or url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('set EVAL_JUDGE_MODEL and EVAL_JUDGE_BASE_URL (OpenAI-compatible API base, e.g. http://host:8000/v1)')
    if url.path.endswith('/chat/completions'):
        raise ValueError('EVAL_JUDGE_BASE_URL must be the API base, not /chat/completions')
    return dict(model=model, base_url=base_url, api_key=os.environ.get('EVAL_JUDGE_API_KEY') or 'EMPTY')


def disable_telemetry():
    # Set before either SDK is imported. Standalone metrics avoid cloud evaluate/upload APIs.
    os.environ['RAGAS_DO_NOT_TRACK'] = 'true'
    os.environ['DEEPEVAL_TELEMETRY_OPT_OUT'] = 'YES'
    os.environ['DEEPEVAL_UPDATE_WARNING_OPT_OUT'] = 'YES'
    os.environ['DEEPEVAL_DISABLE_DOTENV'] = '1'


class RagasJudge:
    def __init__(self, config):
        import instructor
        from openai import AsyncOpenAI
        from ragas.llms import llm_factory
        from ragas.metrics.collections import Faithfulness, ContextRecall
        self.client = AsyncOpenAI(**{k: v for k, v in config.items() if k != 'model'}, timeout=60, max_retries=1)
        llm = llm_factory(config['model'], client=self.client, mode=instructor.Mode.JSON, temperature=0, max_retries=1)
        self.faithfulness, self.recall = Faithfulness(llm=llm), ContextRecall(llm=llm)

    async def score(self, row):
        if not row['retrieved_contexts']:
            return {}, ['faithfulness: no retrieved_contexts', 'context_recall: no retrieved_contexts']
        result = await self.faithfulness.ascore(user_input=row['user_input'], response=row['response'], retrieved_contexts=row['retrieved_contexts'])
        scores = {'faithfulness': result.value}
        skipped = []
        if row.get('reference'):
            result = await self.recall.ascore(user_input=row['user_input'], reference=row['reference'], retrieved_contexts=row['retrieved_contexts'])
            scores['context_recall'] = result.value
        else:
            skipped.append('context_recall: no reference')
        return scores, skipped

    async def close(self):
        await self.client.close()


class DeepEvalJudge:
    def __init__(self, config):
        from deepeval.models import DeepEvalBaseLLM
        from openai import OpenAI, AsyncOpenAI

        class CompatibleModel(DeepEvalBaseLLM):
            def load_model(self):
                return self

            def get_model_name(self):
                return config['model']

            def generate(self, prompt, schema=None):
                result = sync.chat.completions.create(**payload(prompt))
                content = result.choices[0].message.content
                return schema.model_validate_json(content) if schema else content

            async def a_generate(self, prompt, schema=None):
                result = await client.chat.completions.create(**payload(prompt))
                content = result.choices[0].message.content
                return schema.model_validate_json(content) if schema else content

        def payload(prompt):
            return dict(model=config['model'], temperature=0, response_format={'type': 'json_object'},
                        messages=[{'role': 'user', 'content': prompt + '\nReturn only a JSON object.'}])

        kwargs = {k: v for k, v in config.items() if k != 'model'}
        self.sync = sync = OpenAI(**kwargs, timeout=60, max_retries=1)
        self.client = client = AsyncOpenAI(**kwargs, timeout=60, max_retries=1)
        self.model = CompatibleModel(config['model'])

    async def score(self, row):
        from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric
        from deepeval.test_case import LLMTestCase
        case = LLMTestCase(input=row['user_input'], actual_output=row['response'],
                           expected_output=row.get('reference'), retrieval_context=row['retrieved_contexts'] or None)
        scores, skipped = {}, []
        metrics = [('answer_relevancy', AnswerRelevancyMetric)]
        if row['retrieved_contexts']:
            metrics.append(('faithfulness', FaithfulnessMetric))
        else:
            skipped.append('faithfulness: no retrieved_contexts')
        for name, factory in metrics:
            metric = factory(model=self.model, include_reason=False)
            await metric.a_measure(case)
            scores[name] = metric.score
        return scores, skipped

    async def close(self):
        self.sync.close()
        await self.client.close()


async def evaluate(cases, judges, threshold, timeout):
    rows = []
    for case in cases:
        for framework, judge in judges.items():
            row = {'id': case['id'], 'framework': framework, 'scores': {}, 'skipped': [], 'passed': False}
            try:
                scores, skipped = await asyncio.wait_for(judge.score(case), timeout=timeout)
                if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in scores.values()):
                    raise ValueError('invalid metric score')
                row.update(scores=scores, skipped=skipped, passed=bool(scores) and all(v >= threshold for v in scores.values()))
                if not scores:
                    row['error'] = 'no applicable metrics'
            except Exception as exc:
                # SDK errors may contain credentials, prompts or patient data; store only the type.
                row['error'] = type(exc).__name__
            rows.append(row)
    return {'schema_version': 1, 'threshold': threshold, 'passed': bool(rows) and all(r['passed'] for r in rows), 'results': rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--framework', choices=['ragas', 'deepeval', 'both'], default='both')
    parser.add_argument('--output', type=Path, default=Path('test-results/ai-eval.json'))
    parser.add_argument('--threshold', type=float, default=0.7)
    parser.add_argument('--timeout', type=float, default=180)
    parser.add_argument('--validate-only', action='store_true', help='Validate dataset without SDKs or model requests')
    args = parser.parse_args(argv)
    if not math.isfinite(args.threshold) or not 0 <= args.threshold <= 1 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('threshold must be in [0,1]; timeout must be positive and finite')
    if args.dataset.resolve() == args.output.resolve():
        parser.error('output must not overwrite the dataset')
    try:
        cases = load_cases(args.dataset)
        if args.validate_only:
            print(f'Validated {len(cases)} cases; no model requests made.')
            return 0
        config = judge_config()
        disable_telemetry()

        async def run():
            judges = {}
            try:
                if args.framework in ('ragas', 'both'):
                    judges['ragas'] = RagasJudge(config)
                if args.framework in ('deepeval', 'both'):
                    judges['deepeval'] = DeepEvalJudge(config)
                report = await evaluate(cases, judges, args.threshold, args.timeout)
                report['judge_model'] = config['model']
                report['versions'] = {name: version(name) for name in judges}
                return report
            finally:
                for judge in judges.values():
                    await judge.close()

        report = asyncio.run(run())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        print(f"{'PASS' if report['passed'] else 'FAIL'}: {len(report['results'])} evaluations; report: {args.output}")
        return 0 if report['passed'] else 1
    except Exception as exc:
        print(f'Evaluation failed ({type(exc).__name__}); check dataset, optional dependencies and judge configuration.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
