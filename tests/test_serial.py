import json
import unittest
from robot_platform.serial_driver import SerialTelemetry

class Port:
    is_open = True
    def __init__(self): self.data = b''; self.fail = False
    @property
    def in_waiting(self):
        if self.fail: raise OSError('unplugged')
        return len(self.data)
    def read(self, n):
        data, self.data = self.data[:n], self.data[n:]
        return data
    def close(self): self.is_open = False

class SerialTest(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.port = Port()
        self.driver = SerialTelemetry({'port': 'COM3'}, serial_factory=lambda *a, **k: self.port, clock=lambda: self.now)
    def send(self, **values):
        self.port.data += json.dumps({'type':'telemetry', **values}).encode() + b'\n'
        return self.driver.observe()
    def test_legacy_cannot_claim_sensor_freshness(self):
        state = self.send(dist=125, brake=False)
        self.assertEqual(state['distance_m'], 1.25)
        self.assertIsNone(state['strength'])
        self.assertEqual(state['health'], 'unverified')
        self.assertFalse(state['usable'])
        self.now = 2
        self.assertEqual(self.driver.observe()['health'], 'stale')
    def test_sensor_age_and_invalid(self):
        state = self.send(protocol_version=1, distance_cm=100, strength=300, valid=True, sample_age_ms=0)
        self.assertEqual(state['health'], 'ok')
        self.assertTrue(state['usable'])
        state = self.send(protocol_version=1, distance_cm=100, strength=300, valid=True, sample_age_ms=2000)
        self.assertEqual(state['health'], 'stale')
        state = self.send(protocol_version=1, distance_cm=None, valid=False, sample_age_ms=0)
        self.assertEqual(state['health'], 'invalid')
    def test_partial_noise_and_disconnect_recovery(self):
        self.port.data = b'boot log\n{"type":"telemetry","dist":'
        self.assertEqual(self.driver.observe()['health'], 'waiting')
        self.port.data = b'75}\n'
        self.assertEqual(self.driver.observe()['distance_m'], .75)
        self.port.fail = True
        self.assertEqual(self.driver.observe()['health'], 'disconnected')
        self.now = 3
        self.port = Port()
        self.assertEqual(self.driver.observe()['health'], 'waiting')
        self.assertIsNone(self.driver.observe()['distance_m'])
    def test_bad_values_and_bounded_buffer(self):
        for value in [True, float('nan'), -1, 2000]:
            self.send(dist=value)
        self.assertEqual(self.driver.malformed, 4)
        self.port.data = b'x' * 5000
        self.driver.observe()
        self.assertLessEqual(len(self.driver.buffer), 4096)
