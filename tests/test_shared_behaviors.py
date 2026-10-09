import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO
from robot_platform.behaviors import DEFAULTS, settings, configure, BehaviorEngine
from robot_platform.agent import RobotRuntime, Agent
from test_behaviors import reading


def config(**changes):
    return {'schema_version': 1, 'devices': [{'name': 'BodyModule', 'driver': 'bb8-v2',
            'extensions': ['ambient_light', 'illumination']}], **changes}


def rows(active=True):
    return {'BodyModule': {**DEFAULTS, 'enabled': True, 'allow_illumination': active}}


class Driver:
    capabilities = {'illumination': True}
    def __init__(self):self.calls = []
    def command(self, action):
        self.calls.append(action)
        return {'acknowledged': True}


class SharedBehaviorTests(unittest.TestCase):
    def test_setup_preserves_ai_policy_and_cancellation(self):
        c = config(ai_backend={'model': 'qwen3:8b'}, ai_capabilities={'actions': {'set_illumination': False}})
        answers = ['y', 'y', '15', '40', '3', '20', 'y']
        saved = []
        with patch('builtins.input', side_effect=answers), redirect_stdout(StringIO()):
            self.assertTrue(configure('unused', c, lambda p, d: saved.append(d), 'BodyModule'))
        self.assertEqual(saved[0]['ai_backend'], c['ai_backend'])
        self.assertEqual(saved[0]['ai_capabilities'], c['ai_capabilities'])
        self.assertEqual(saved[0]['behaviors']['BodyModule']['dark'], 15)
        self.assertNotIn('behaviors', c)
        with patch('builtins.input', side_effect=['n', 'n']), redirect_stdout(StringIO()):
            self.assertFalse(configure('unused', c, lambda *a: self.fail('saved'), 'BodyModule'))

    def test_validation_defaults_and_invalid_permissions(self):
        self.assertEqual(settings(config()), {})
        for overrides in [{'enabled': 'yes'}, {'enabled': True, 'allow_illumination': 1}, {'unknown': 1}, {'bright': 5}]:
            with self.assertRaises(ValueError):settings(config(behaviors={'BodyModule': overrides}))
        with self.assertRaises(ValueError):settings(config(behaviors={'Other': {}}))
        c = config(behaviors=rows());c['devices'][0]['extensions'] = []
        with self.assertRaises(ValueError):settings(c)

    def test_saved_preview_and_missing_device_never_write(self):
        d = Driver(); now = [0]
        for devices in ({'BodyModule': d}, {}):
            engine = BehaviorEngine(rows(False), devices, trace=lambda s: None, clock=lambda: now[0])
            state = {'devices': {'BodyModule': {'observation': reading()}}}
            now[0] = 0;engine.step(state)
            now[0] = 2;engine.step(state)
        self.assertEqual(d.calls, [])

    def test_manual_command_pauses_autonomy_until_explicit_resume(self):
        d = Driver()
        runtime = RobotRuntime({'BodyModule': d}, lambda ds: {'devices': {'BodyModule': {'observation': reading()}}}, rows())
        now = [0];runtime.behaviors.clock = lambda: now[0]
        runtime.behaviors.trace = lambda s: None
        runtime.behaviors.step(runtime.state())
        runtime.illumination('BodyModule', False)
        now[0] = 3;runtime.behaviors.step(runtime.state())
        self.assertEqual(len(d.calls), 1)
        self.assertEqual(runtime.behavior_state()['paused_devices'], ['BodyModule'])
        runtime.resume_behaviors()
        runtime.behaviors.step(runtime.state())
        now[0] = 5;runtime.behaviors.step(runtime.state())
        self.assertEqual([a['on'] for a in d.calls], [False, True])

    def test_paused_status_events_are_bounded_and_detached(self):
        d = Driver();now = [0]
        engine = BehaviorEngine(rows(), {'BodyModule': d}, trace=lambda s: None, clock=lambda: now[0])
        for index in range(25):
            level = 5 if index % 2 == 0 else 80
            obs = reading(level, on=level > 35)
            state = {'devices': {'BodyModule': {'observation': obs}}}
            now[0] = index * 20;engine.step(state)
            now[0] += 2;engine.step(state)
        self.assertEqual(len(engine.state()['recent_events']), 20)
        state = engine.state();state['settings']['BodyModule']['enabled'] = False
        self.assertTrue(engine.rows['BodyModule']['enabled'])
        engine.pause();engine.step({})
        self.assertEqual(engine.state()['latest']['BodyModule']['status'], 'paused')

    def test_default_runtime_and_denied_ai_cannot_start_behaviors(self):
        d = Driver();runtime = RobotRuntime({'BodyModule': d}, lambda ds: {'devices': {}})
        self.assertEqual(runtime.behavior_state()['settings'], {})
        agent = Agent(None, runtime, trace=lambda s: None,
                      permissions={'actions': {'set_illumination': False}})
        self.assertIn('error', agent.execute('set_illumination', {'device': 'BodyModule', 'on': True}, [False]))
        self.assertEqual(d.calls, [])

    def test_behavior_and_manual_calls_share_lock_and_shutdown_waits(self):
        import threading
        entered = threading.Event();release = threading.Event();manual_done = threading.Event()
        class BlockingDriver(Driver):
            def command(self, action):
                self.calls.append(action)
                if len(self.calls) == 1:
                    entered.set()
                    if not release.wait(2):raise ValueError('test command stalled')
                return {'acknowledged': True}
        d = BlockingDriver();now = [0]
        runtime = RobotRuntime({'BodyModule': d}, lambda ds: {'devices': {'BodyModule': {'observation': reading()}}}, rows())
        runtime.behaviors.clock = lambda: now[0];runtime.behaviors.trace = lambda s: None
        runtime.behaviors.step(runtime.state());now[0] = 2
        runtime.start()
        try:
            self.assertTrue(entered.wait(2))
            def manual():
                runtime.illumination('BodyModule', False);manual_done.set()
            thread = threading.Thread(target=manual);thread.start()
            self.assertFalse(manual_done.wait(.05))
            release.set();thread.join(2)
            self.assertTrue(manual_done.is_set())
            self.assertEqual([a['on'] for a in d.calls], [True, False])
            self.assertEqual(runtime.behavior_state()['paused_devices'], ['BodyModule'])
        finally:
            release.set();runtime.close()
        self.assertFalse(runtime.worker.is_alive())
