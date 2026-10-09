import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO
from robot_platform.reactions import RangeChanges, Temperament, DEFAULTS, settings, configure
from robot_platform.behaviors import BehaviorEngine
from robot_platform.agent import RobotRuntime
from robot_platform.live import run_live
from robot_platform.service import unit


def reading(distance=1, receipt='1', **changes):
    return {'usable': True, 'distance_m': distance, 'received_at': receipt, **changes}


def rows(active=True, profile='cat'):
    return {'RangeSensor': {**DEFAULTS, 'enabled': True, 'allow_buzzer': active, 'profile': profile}}


class Driver:
    capabilities = {'mood': True}
    def __init__(self):self.calls = []
    def command(self, action):
        self.calls.append(action);return {'acknowledged': False}


class ReactionTests(unittest.TestCase):
    def test_startup_quiet_and_settled_change(self):
        r = RangeChanges()
        self.assertEqual(r.update(reading(), 0)['status'], 'baseline')
        self.assertEqual(r.update(reading(.4, '2'), 1)['status'], 'settling')
        self.assertEqual(r.update(reading(.4, '3'), 1.5)['status'], 'settling')
        event = r.update(reading(.4, '4'), 1.8)['event']
        self.assertEqual(event['delta_m'], -.6)
        self.assertIn('object identity unknown', event['meaning'])
        self.assertIsNone(r.update(reading(.4, '5'), 2)['event'])

    def test_duplicate_stale_and_reconnect_never_trigger(self):
        r = RangeChanges();r.update(reading(), 0);r.update(reading(.4, '2'), 1)
        self.assertEqual(r.update(reading(.4, '2'), 5)['status'], 'waiting_for_new_sample')
        r.update(reading(usable=False), 6)
        self.assertEqual(r.update(reading(.4, '3'), 7)['status'], 'baseline')
        self.assertIsNone(r.update(reading(.4, '4'), 10)['event'])
        for changes in [{'distance_m': float('nan')}, {'distance_m': True},
                        {'head_link_valid': False}, {'received_at': None}, {'distance_m': 0}]:
            self.assertEqual(r.update(reading(**changes), 20)['status'], 'unavailable')

    def test_noise_cooldown_keeps_perception_but_never_queues_sound(self):
        r = RangeChanges();r.update(reading(), 0)
        self.assertEqual(r.update(reading(.98, '2'), .5)['status'], 'steady')
        r.update(reading(.4, '3'), 1)
        self.assertTrue(r.update(reading(.4, '4'), 2)['event']['reaction_allowed'])
        r.update(reading(1, '5'), 3)
        decision = r.update(reading(1, '6'), 4)
        self.assertEqual(decision['status'], 'cooldown')
        self.assertFalse(decision['event']['reaction_allowed'])
        self.assertIsNone(r.update(reading(1, '7'), 40)['event'])

    def test_presets_have_distinct_intentions_and_bird_waits_for_clearance(self):
        close = {'delta_m': -.6, 'previous_distance_m': 1, 'distance_m': .4}
        partial = {'delta_m': .3, 'previous_distance_m': .4, 'distance_m': .7}
        clear = {'delta_m': .3, 'previous_distance_m': .7, 'distance_m': 1}
        cat, bird, shy = [Temperament(p) for p in ('cat', 'bird', 'shy')]
        self.assertEqual(cat.decide(close)['intent'], 'investigate_change')
        self.assertEqual(bird.decide(close)['intent'], 'give_space')
        self.assertEqual(bird.decide(partial)['intent'], 'wait_at_distance')
        self.assertEqual(bird.decide(clear)['intent'], 'reengage')
        self.assertEqual(shy.decide(close)['intent'], 'give_space')
        self.assertIsNone(shy.decide(clear)['sound'])
        self.assertFalse(cat.decide(close)['movement']['executed'])
        bird.decide(close);bird.reset()
        self.assertEqual(bird.decide(clear)['intent'], 'continue_exploring')

    def test_setup_preserves_settings_and_supports_other_driver(self):
        c = {'devices': [{'name': 'RangeSensor', 'driver': 'third-party-range'}],
             'ai_backend': {'model': 'test'}, 'behaviors': {}}
        saved = []
        with patch('robot_platform.drivers.registry', return_value={'third-party-range': Driver}), patch('builtins.input', side_effect=['y', '2', 'n', '', '', '', 'y']), redirect_stdout(StringIO()):
            self.assertTrue(configure('unused', c, lambda p, d: saved.append(d), 'RangeSensor'))
        row = settings(saved[0])['RangeSensor']
        self.assertEqual(row['profile'], 'bird');self.assertFalse(row['allow_buzzer'])
        self.assertEqual(saved[0]['ai_backend'], c['ai_backend']);self.assertNotIn('reactions', c)
        for overrides in [{'enabled': 'y'}, {'allow_buzzer': 1}, {'profile': 'dog'}, {'cooldown_s': 0}, {'change_m': float('inf')}]:
            with self.assertRaises(ValueError):settings({**c, 'reactions': {'RangeSensor': overrides}})
        with patch('robot_platform.drivers.registry', return_value={'third-party-range': Driver}), patch('builtins.input', side_effect=['n', 'n']), redirect_stdout(StringIO()):
            self.assertFalse(configure('unused', c, lambda *a: self.fail('saved'), 'RangeSensor'))

    def test_preview_and_failed_action_never_retry(self):
        for active in (False, True):
            now = [0];d = Driver();events = []
            engine = BehaviorEngine({}, {'RangeSensor': d}, trace=events.append, clock=lambda: now[0], reactions=rows(active))
            for t, dist, receipt in [(0, 1, '1'), (1, .4, '2'), (2, .4, '3'), (40, .4, '4')]:
                now[0] = t;engine.step({'devices': {'RangeSensor': {'observation': reading(dist, receipt)}}})
            self.assertEqual(len(d.calls), 1 if active else 0);self.assertEqual(len(events), 1)
            engine.pause();self.assertEqual(engine.state()['paused_devices'], ['RangeSensor'])
            engine.resume();now[0] = 45
            engine.step({'devices': {'RangeSensor': {'observation': reading(.4, '5')}}})
            self.assertEqual(engine.state()['reaction_latest']['RangeSensor']['status'], 'baseline')

    def test_unsupported_output_reports_intent_without_writing(self):
        d = Driver();d.capabilities = {};now = [0]
        engine = BehaviorEngine({}, {'RangeSensor': d}, trace=lambda s: None, clock=lambda: now[0], reactions=rows())
        for t, dist, receipt in [(0, 1, '1'), (1, .4, '2'), (2, .4, '3')]:
            now[0] = t;engine.step({'devices': {'RangeSensor': {'observation': reading(dist, receipt)}}})
        self.assertEqual(d.calls, [])
        self.assertEqual(engine.state()['recent_events'][-1]['plan']['intent'], 'investigate_change')

    def test_manual_mood_pauses_and_live_needs_no_ai(self):
        d = Driver();runtime = RobotRuntime({'RangeSensor': d}, lambda ds: {}, reaction_settings=rows())
        runtime.mood('RangeSensor', 'happy')
        self.assertEqual(runtime.behavior_state()['paused_devices'], ['RangeSensor'])
        c = {'devices': [{'name': 'RangeSensor', 'driver': 'third-party-range'}], 'reactions': rows(False)}
        output = []
        run_live(c, {'RangeSensor': d}, lambda ds: {'devices': {'RangeSensor': {'observation': reading()}}}, output.append, ticks=1)
        self.assertFalse(output[0]['ai_required']);self.assertEqual(len(d.calls), 1)

    def test_live_service_mode_and_invalid_options(self):
        with patch('robot_platform.service.platform.system', return_value='Linux'):
            text = unit('/tmp/robot.json', ['RangeSensor'], mode='live')
            self.assertIn('"live"', text);self.assertNotIn('"chat"', text)
            with self.assertRaises(ValueError):unit('/tmp/robot.json', [], mode='other')
        with self.assertRaises(ValueError):run_live({'devices': []}, {}, lambda ds: {}, print, ticks=1)
