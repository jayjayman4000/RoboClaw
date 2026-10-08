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
            self.invoke(path, ['', 'y', '3', 'lidar', 'n', 'y', 'n'])
            data = json.loads(path.read_text())
            self.assertEqual(len(data['devices']), 1)
            original = path.read_bytes()
            self.invoke(path, ['y', 'changed', 'n', 'n'])
            self.assertEqual(path.read_bytes(), original)

    def test_installed_plugin_appears_in_menu(self):
        from robot_platform.drivers import SimRange
        from robot_platform.setup import select_device
        with patch('builtins.input', side_effect=['1', 'custom_range']):
            device = select_device({'third-party-range': SimRange}, [])
        self.assertEqual(device['driver'], 'third-party-range')

    def test_windows_port_numbers_are_normalized(self):
        from robot_platform.setup import normalize_windows_port, settings
        from robot_platform.serial_driver import SerialTelemetry
        self.assertEqual(normalize_windows_port('4'), 'COM4')
        self.assertEqual(normalize_windows_port(' com05 '), 'COM5')
        with patch('robot_platform.setup.os.name', 'nt'):
            self.assertEqual(settings(SerialTelemetry, {'port': '5'}, interactive=False)['port'], 'COM5')
        with self.assertRaises(ValueError): normalize_windows_port('COM0')
