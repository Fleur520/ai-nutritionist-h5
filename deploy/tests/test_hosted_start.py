import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock, patch


def module():
    spec = importlib.util.spec_from_file_location('hosted_start', Path(__file__).resolve().parents[1] / 'hosted_start.py')
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


class HostedAcceptanceGateTests(unittest.TestCase):
    def exercise(self, fail):
        start = module()
        process = Mock()
        process.poll.return_value = None
        response = Mock()
        response.__enter__ = Mock(return_value=Mock(status=200))
        response.__exit__ = Mock(return_value=False)
        acceptance = []
        def run(command, **kwargs):
            if 'hosted_acceptance.py' in ' '.join(command):
                acceptance.append('checked')
                if fail:
                    raise subprocess.CalledProcessError(1, command)
        def expose(*args):
            self.assertEqual(acceptance, ['checked'])
            process.terminate.assert_called_once()
        with patch.object(start.subprocess, 'run', side_effect=run), patch.object(start.subprocess, 'Popen', return_value=process), patch.object(start.urllib.request, 'urlopen', return_value=response), patch.object(start.os, 'execv', side_effect=expose) as activate:
            if fail:
                with self.assertRaises(subprocess.CalledProcessError):
                    start.main()
                activate.assert_not_called()
            else:
                start.main()
                activate.assert_called_once()
            process.terminate.assert_called_once()

    def test_failed_acceptance_never_exposes_candidate(self):
        self.exercise(True)

    def test_successful_acceptance_precedes_public_startup(self):
        self.exercise(False)
