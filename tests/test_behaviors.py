import unittest
from robot_platform.behaviors import Darkness, run


def reading(level=5, on=False, **changes):
    return {'light_usable': True, 'illumination_state_usable': True,
            'light_percent': level, 'illumination_on': on, **changes}


class DarknessTests(unittest.TestCase):
    def test_sustained_darkness_and_brightness_with_cooldown(self):
        b = Darkness()
        self.assertIsNone(b.update(reading(), 0)['request'])
        self.assertTrue(b.update(reading(), 2)['request'])
        self.assertIsNone(b.update(reading(), 3)['request'])
        b.update(reading(80, True), 4)
        self.assertEqual(b.update(reading(80, True), 6)['status'], 'cooldown')
        self.assertFalse(b.update(reading(80, True), 12)['request'])
    def test_stale_sample_breaks_dwell_and_reconnect_does_not_replay(self):
        b = Darkness()
        b.update(reading(), 0)
        b.update(reading(light_usable=False), 1)
        self.assertIsNone(b.update(reading(), 2)['request'])
        self.assertTrue(b.update(reading(), 4)['request'])
        b.update(reading(illumination_state_usable=False), 5)
        b.update(reading(), 20)
        self.assertIsNone(b.update(reading(), 23)['request'])
    def test_hysteresis_and_existing_state_do_not_write(self):
        b = Darkness()
        b.update(reading(), 0)
        b.update(reading(25), 1)
        b.update(reading(), 2)
        self.assertIsNone(b.update(reading(), 3)['request'])
        self.assertIsNone(b.update(reading(on=True), 4)['request'])
    def test_invalid_values_and_no_fresh_output_state(self):
        for changes in [{'light_percent': float('nan')}, {'light_percent': True},
                        {'light_percent': -1}, {'illumination_on': None}, {'light_usable': False}]:
            self.assertEqual(Darkness().update(reading(**changes), 0)['status'], 'unavailable')
        for args in [(35, 20), (0, 101), (20, 35, 0), (20, 35, 2, float('nan'))]:
            with self.assertRaises(ValueError): Darkness(*args)
    def test_preview_never_dispatches_and_failed_action_never_retries(self):
        from unittest.mock import patch
        class Driver:
            calls = 0
            def observe(self): return reading()
            def command(self, request):
                self.calls += 1
                return {'acknowledged': False}
        for execute in (False, True):
            d = Driver(); events = []
            with patch('robot_platform.behaviors.time.monotonic', side_effect=[0, 2, 12]), patch('robot_platform.behaviors.time.sleep'):
                run(d, 'BodyModule', events.append, execute=execute, ticks=3)
            self.assertEqual(d.calls, 1 if execute else 0)
            self.assertEqual(events[1]['decision']['request'], True)
