import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from robot_platform.bb8_bridge import BB8Bridge
from robot_platform.cli import main, save
from robot_platform.hardware import configure
from test_moods import MoodPort


class DroidLanguageTest(unittest.TestCase):
    def make(self, events=None, supported=True):
        self.now = 0
        self.port = MoodPort(events or [])
        telemetry = {
            'type': 'telemetry', 'dist': None, 'sensor_valid': False,
            'head_connected': True, 'strength': None, 'sample_age_ms': None,
            'seq': 1, 'rx_overwrites': 0, 'sound_supported': supported,
            'light_supported': True, 'illumination_supported': True,
            'light_raw': 2048, 'light_age_ms': 5, 'illumination_on': False,
        }
        self.port.data = json.dumps(telemetry).encode() + b'\n'
        self.driver = BB8Bridge(
            {'port': 'virtual', 'extensions': ['droid_language']},
            serial_factory=lambda *a, **k: self.port,
            clock=lambda: self.now,
        )
        self.driver.sleep = lambda seconds: setattr(self, 'now', self.now + seconds)
        return self.driver

    def test_pi_sends_named_sound_and_requires_matching_head_ack(self):
        driver = self.make([
            {'type': 'command_sent', 'id': 12, 'accepted_by_radio': True},
            {'type': 'sound_ack', 'id': 12, 'sound': 0},
        ])

        result = driver.command({'action': 'sound', 'sound': 'hello', 'timeout': .2})

        self.assertEqual(self.port.writes, [b'sound hello\n'])
        self.assertEqual(result['status'], 'acknowledged')
        self.assertTrue(result['acknowledged'])
        self.assertEqual(result['sound'], 'hello')

    def test_cli_exposes_named_droid_sound(self):
        calls = []

        class FakeBridge:
            fields = {}

            def __init__(self, config):
                pass

            def command(self, action):
                calls.append(action)
                return {'acknowledged': True, 'status': 'acknowledged'}

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / 'robot.json'
            save(config_path, {'schema_version': 1, 'robot': 'BB-2e', 'devices': [
                {'name': 'BodyModule', 'driver': 'bb8-v2', 'enabled': True,
                 'extensions': ['droid_language']},
            ]})
            with patch('robot_platform.cli.registry', return_value={'bb8-v2': FakeBridge}), redirect_stdout(StringIO()):
                status = main(['--config', str(config_path), 'sound', 'BodyModule', 'question', '--timeout', '.2'])

        self.assertEqual(status, 0)
        self.assertEqual(calls, [{'action': 'sound', 'sound': 'question', 'timeout': .2}])

    def test_hardware_setup_detects_language_without_light_hardware(self):
        driver = self.make()
        self.port.data = json.dumps({
            'type': 'telemetry', 'dist': None, 'sensor_valid': False,
            'head_connected': True, 'strength': None, 'sample_age_ms': None,
            'seq': 1, 'rx_overwrites': 0, 'sound_supported': True,
        }).encode() + b'\n'
        config = {'devices': [{'name': 'BodyModule', 'driver': 'bb8-v2', 'port': 'virtual'}]}
        saved = []
        with patch('builtins.input', side_effect=['y', 'y']), redirect_stdout(StringIO()):
            configured = configure(
                'unused', config, lambda path, value: saved.append(value), 'BodyModule',
                timeout=.2, driver_factory=lambda candidate: driver,
            )
        self.assertTrue(configured)
        self.assertEqual(saved[0]['devices'][0]['extensions'], ['droid_language'])


if __name__ == '__main__':
    unittest.main()
