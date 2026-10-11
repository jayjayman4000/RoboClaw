import threading
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO
from robot_platform.autonomy import AutonomousDecisions, settings, configure
from robot_platform.agent import RobotRuntime


def observation(distance=1, receipt='1', **changes):
    return {'distance_m': distance, 'usable': True, 'received_at': receipt,
            'light_percent': 60, 'light_usable': True, 'illumination_state_usable': True,
            'illumination_on': False, **changes}


def response(action='mood', **args):
    return {'tool_calls': [{'function': {'name': 'choose_action',
            'arguments': {'action': action, 'reason': 'range changed', **args}}}]}


class Driver:
    capabilities = {'mood': True, 'illumination': True}
    def __init__(self):self.calls = []
    def command(self, action):
        self.calls.append(action);return {'acknowledged': True}


class Backend:
    def __init__(self, result=None, callback=None):self.result = result or response(mood='curious');self.callback = callback;self.calls = 0
    def complete(self, messages, tools):
        self.calls += 1
        if self.callback:self.callback()
        return self.result


class AutonomyTests(unittest.TestCase):
    def make(self, backend=None, permissions=None, auto=None):
        self.now = 0;self.obs = observation(.4, '3');self.driver = Driver()
        self.runtime = RobotRuntime({'range': self.driver}, lambda ds: {'devices': {'range': {'observation': dict(self.obs)}}})
        c = {'devices': [{'name': 'range', 'driver': 'test'}],
             'autonomous_ai': {'enabled': True, 'allow_buzzer': True, 'allow_illumination': True, **(auto or {})}}
        if permissions is not None:c['ai_capabilities'] = permissions
        self.auto = AutonomousDecisions(c, self.runtime, backend or Backend(), trace=lambda s: None, clock=lambda: self.now)
        self.auto.generation['range'] = 1
        return {'device': 'range', 'event': {'type': 'range_changed'},
                'observation': dict(self.obs), 'created': 0, 'generation': 1}

    def test_one_inference_and_one_output(self):
        backend = Backend();event = self.make(backend)
        report = self.auto.decide(event)
        self.assertEqual(backend.calls, 1);self.assertEqual(len(self.driver.calls), 1)
        self.assertEqual(report['status'], 'executed')
        self.assertEqual(self.auto.decide(event)['status'], 'output_cooldown')
        self.assertEqual(len(self.driver.calls), 1)

    def test_slow_or_changed_response_discarded(self):
        for change in ('slow', 'changed', 'paused', 'stopped', 'superseded'):
            def callback():
                if change == 'slow':self.now = 4
                elif change == 'changed':self.obs['distance_m'] = 2
                elif change == 'paused':self.auto.pause(['range'])
                elif change == 'stopped':self.auto.stop.set()
                else:self.auto.generation['range'] += 1
            event = self.make(Backend(callback=callback))
            self.assertEqual(self.auto.decide(event)['status'], 'discarded_stale')
            self.assertEqual(self.driver.calls, [])

    def test_no_action_and_forged_tools(self):
        event = self.make(Backend(response('none')))
        self.assertEqual(self.auto.decide(event)['status'], 'no_action');self.assertEqual(self.driver.calls, [])
        for result in [response('mood', mood='alarm'), response('mood', mood='curious', extra=1),
                       response('illumination', on=1), response('move'), {'tool_calls': []},
                       {'tool_calls': [{'function': {'name': 'shell', 'arguments': {}}}]}]:
            event = self.make(Backend(result))
            with self.assertRaises(ValueError):self.auto.decide(event)
            self.assertEqual(self.driver.calls, [])

    def test_ai_permissions_and_local_owners_cannot_be_bypassed(self):
        event = self.make(permissions={'actions': {'set_buzzer_mood': False}})
        self.assertNotIn('mood', self.auto.actions('range'))
        with self.assertRaises(ValueError):self.auto.decide(event)
        self.make();self.runtime.behaviors.rows['range'] = {'allow_illumination': True}
        self.runtime.behaviors.reactions['range'] = {'allow_buzzer': True}
        self.assertEqual(self.auto.actions('range'), ['none'])
        self.make(auto={'allow_buzzer': False, 'allow_illumination': False})
        self.assertEqual(self.auto.actions('range'), ['none'])

    def test_queue_is_latest_only_and_sensor_access_denied(self):
        self.make()
        for t, d, receipt in [(0, 1, '1'), (1, .4, '2'), (2, .4, '3'), (3, 1, '4'), (4, 1, '5')]:
            self.now = t;self.auto.feed({'devices': {'range': {'observation': observation(d, receipt)}}})
        self.assertEqual(self.auto.pending['observation']['distance_m'], 1)
        self.assertGreater(self.auto.pending['generation'], 1)
        self.auto.permissions = {'actions': {'read_robot_state': False}};self.auto.pending = None
        self.auto.feed({'devices': {'range': {'observation': observation(.2, '6')}}})
        self.assertIsNone(self.auto.pending)

    def test_disconnect_and_recovery_invalidates_inflight_decision(self):
        event = self.make()
        self.auto.feed({'devices': {'range': {'observation': dict(self.obs)}}})
        self.auto.feed({'devices': {'range': {'observation': observation(usable=False)}}})
        self.auto.feed({'devices': {'range': {'observation': dict(self.obs)}}})
        self.assertFalse(self.auto.valid(event, self.obs))
        self.assertEqual(self.driver.calls, [])

    def test_model_wait_does_not_hold_runtime_lock(self):
        entered = threading.Event();release = threading.Event()
        def block():
            entered.set()
            if not release.wait(2):raise ValueError('test timeout')
        event = self.make(Backend(callback=block));results = []
        worker = threading.Thread(target=lambda: results.append(self.auto.decide(event)));worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self.assertTrue(self.runtime.lock.acquire(timeout=.1));self.runtime.lock.release()
            self.runtime.mood('range', 'happy')
            self.auto.pause(['range'])
        finally:release.set();worker.join(2)
        self.assertEqual(results[0]['status'], 'discarded_stale')
        self.assertEqual(len(self.driver.calls), 1)

    def test_light_decisions_require_same_zone_and_fresh_output(self):
        event = self.make(Backend(response('illumination', on=True)))
        self.obs.update(light_percent=5);event['event'] = {'type': 'light_changed', 'zone': 'dark'}
        self.assertEqual(self.auto.decide(event)['status'], 'executed')
        event = self.make(Backend(response('illumination', on=True)))
        event['event'] = {'type': 'light_changed', 'zone': 'dark'}
        self.assertEqual(self.auto.decide(event)['status'], 'discarded_stale')
        self.assertEqual(self.driver.calls, [])

    def test_setup_cancellation_defaults_and_fast_backend(self):
        self.assertFalse(settings({})['enabled'])
        for overrides in [{'enabled': 'y'}, {'decision_budget_s': float('nan')}, {'min_interval_s': 0}]:
            with self.assertRaises(ValueError):settings({'autonomous_ai': overrides})
        c = {'devices': [], 'ai_backend': {'provider': 'ollama', 'model': 'qwen3:8b'}}
        with patch('builtins.input', side_effect=['n', 'n']), redirect_stdout(StringIO()):
            self.assertFalse(configure('unused', c, lambda *a: self.fail('saved')))
        fake = Backend()
        with patch('robot_platform.ai_backend.backend_from_settings', return_value=fake):
            runtime = RobotRuntime({}, lambda ds: {})
            runtime.enable_autonomy({**c, 'autonomous_ai': {'enabled': True}})
        self.assertEqual(fake.timeout_s, 3);self.assertEqual(fake.num_predict, 128)

    def test_operator_turn_preempts_decision_and_has_no_event_backlog(self):
        event = self.make()
        self.auto.begin_operator_turn()
        self.auto.feed({'devices': {'range': {'observation': observation(.4, '3')}}})
        self.assertIsNone(self.auto.pending)
        self.assertEqual(self.auto.decide(event)['status'], 'discarded_stale')
        self.assertEqual(self.auto.backend.calls, 0)
        self.auto.end_operator_turn()
        self.auto.feed({'devices': {'range': {'observation': observation(.4, '4')}}})
        self.assertIsNone(self.auto.pending)
        self.assertEqual(self.driver.calls, [])

    def test_worker_executes_once_and_error_backoff_has_no_retry(self):
        completed = threading.Event();reports = []
        event = self.make()
        self.auto.trace = lambda report: (reports.append(report), completed.set())
        self.auto.pending = event
        self.auto.start()
        try:
            self.auto.wake.set()
            self.assertTrue(completed.wait(2))
            self.assertEqual(len(self.driver.calls), 1)
            self.assertFalse(self.auto.state()['pending'])
        finally:self.auto.close()
        self.assertFalse(self.auto.worker.is_alive())
        def fail():raise OSError('model unavailable')
        event = self.make(Backend(callback=fail));completed.clear()
        self.auto.trace = lambda report: completed.set()
        self.auto.pending = event;self.auto.start()
        try:
            self.auto.wake.set();self.assertTrue(completed.wait(2))
            self.assertGreater(self.auto.retry_after, self.now)
            self.assertEqual(self.auto.backend.calls, 1);self.assertIsNone(self.auto.pending)
        finally:self.auto.close()
        self.assertEqual(self.driver.calls, [])

    def test_service_autonomy_is_explicit_and_live_only(self):
        from robot_platform.service import unit
        with patch('robot_platform.service.platform.system', return_value='Linux'):
            self.assertIn('"--autonomous-ai"', unit('/tmp/robot.json', [], mode='live', autonomous_ai=True))
            self.assertNotIn('--autonomous-ai', unit('/tmp/robot.json', [], mode='live'))
            with self.assertRaises(ValueError):unit('/tmp/robot.json', [], autonomous_ai=True)

    def test_short_ollama_request_is_configured_without_changing_normal_chat(self):
        from robot_platform.ollama_backend import OllamaBackend
        result = {'message': {'role': 'assistant', 'content': '', 'tool_calls': []}}
        regular = OllamaBackend(model='qwen3:8b')
        fast = OllamaBackend(model='qwen3:8b');fast.num_predict=128;fast.num_ctx=2048;fast.keep_alive='10m'
        for backend, tokens, context, keep in [(regular,512,4096,'5m'), (fast,128,2048,'10m')]:
            with patch.object(backend, 'request', return_value=result) as request:
                backend.complete([{'role':'system','content':'choose'}], [])
            payload = request.call_args.args[1]
            self.assertEqual(payload['options']['num_predict'], tokens)
            self.assertEqual(payload['options']['num_ctx'], context)
            self.assertEqual(payload['keep_alive'], keep);self.assertFalse(payload['think'])
