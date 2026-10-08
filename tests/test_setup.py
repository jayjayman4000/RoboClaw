import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from robot_platform.cli import main


class SetupTest(unittest.TestCase):
    def invoke(self, path, answers):
        with patch('builtins.input', side_effect=answers), contextlib.redirect_stdout(io.StringIO()):
            main(['--config', str(path), 'setup'])

    def test_onboarding_and_cancel_preserves_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'robot.json'
            self.invoke(path, ['', '', '', '', '', '', '', ''])
            data = json.loads(path.read_text())
            self.assertEqual(len(data['devices']), 3)
            original = path.read_bytes()
            self.invoke(path, ['', 'changed', '', '', 'n'])
            self.assertEqual(path.read_bytes(), original)

    def test_hardware_is_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'robot.json'
            self.invoke(path, ['', '', '2', '', 'CSI', '', 'COM3', '', 'COM4', ''])
            data = json.loads(path.read_text())
            self.assertTrue(all(not d['enabled'] for d in data['devices']))
            with contextlib.redirect_stdout(io.StringIO()) as output:
                main(['--config', str(path), 'inspect'])
            self.assertEqual(json.loads(output.getvalue())['devices'], {})
