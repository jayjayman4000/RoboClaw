import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from robot_platform.demo import run_demo
from robot_platform.cli import main


class DemoTest(unittest.TestCase):
    def test_parser_health_transitions(self):
        states = list(run_demo())
        observations = [s['observation'] for s in states]
        self.assertEqual([s['health'] for s in observations], [
            'waiting', 'waiting', 'ok', 'ok', 'invalid', 'stale',
            'ok', 'stale', 'disconnected', 'waiting', 'ok', 'unverified'])
        self.assertTrue(all(s['simulation'] for s in states))
        self.assertTrue(all(s['source'] == 'simulation' for s in observations))
        self.assertIsNone(observations[9]['distance_m'])
        self.assertEqual(observations[10]['distance_m'], .8)
        self.assertEqual(observations[3]['malformed_lines'], 2)
        self.assertFalse(observations[-1]['usable'])

    def test_cli_does_not_read_or_modify_robot_config(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'robot.json'
            path.write_text('deliberately invalid config')
            with patch('robot_platform.cli.time.sleep'), redirect_stdout(StringIO()) as output:
                self.assertEqual(main(['--config', str(path), 'demo']), 0)
            self.assertEqual(path.read_text(), 'deliberately invalid config')
            self.assertIn('USB reconnected', output.getvalue())
