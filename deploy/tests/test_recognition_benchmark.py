import asyncio
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

spec = importlib.util.spec_from_file_location('recognition_benchmark', Path(__file__).resolve().parents[1] / 'benchmark_recognition.py')
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class RecognitionBenchmarkTests(unittest.TestCase):
    def test_percentiles_keep_failed_slow_requests(self):
        rows = [{'status': 200, 'seconds': i} for i in range(1, 20)]
        rows.append({'status': 504, 'seconds': 240})
        result = benchmark.summarize(rows)
        self.assertEqual(result, {'requests': 20, 'success': 19, 'p50': 10, 'p95': 19,
                                  'max': 240, 'under_20_seconds': 19})

    def test_no_samples_is_not_a_pass(self):
        with self.assertRaises(ValueError):
            benchmark.summarize([])

    def test_variants_preserve_dimensions_and_change_visual_input(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'scene.jpg'
            Image.new('RGB', (80, 40), (100, 150, 200)).save(path)
            first, second = (benchmark.fixture(path, i, True) for i in (0, 40))
            self.assertNotEqual(first, second)
            self.assertEqual(Image.open(io.BytesIO(first)).size, (80, 40))
            self.assertEqual(benchmark.fixture(path, 0, False), path.read_bytes())

    def test_production_database_is_rejected_before_connection(self):
        config, database = ModuleType('app.config'), ModuleType('app.db')
        config.get_settings = lambda: SimpleNamespace(app_db_engine='mysql', mysql_database='ai_nutritionist')
        database.connect = lambda: self.fail('Must not open the production database')
        with patch.dict(sys.modules, {'app': ModuleType('app'), 'app.config': config, 'app.db': database}):
            with self.assertRaisesRegex(ValueError, 'isolated test_'):
                asyncio.run(benchmark.guarded_database())

    def test_private_report_preserves_structured_result(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'report.json'
            benchmark.private_json(path, {'requests': [], 'label': '真实识别'})
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['label'], '真实识别')


if __name__ == '__main__':
    unittest.main()
