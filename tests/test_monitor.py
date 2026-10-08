import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from contextlib import redirect_stdout
from io import StringIO
from robot_platform.monitor import AIHealth, HealthEvents, probe_ai, watch
from robot_platform.service import unit, quote
from robot_platform.cli import main, snapshot, save
from robot_platform.serial_driver import SerialTelemetry
from test_serial import Port

class MonitorTest(unittest.TestCase):
    def test_ai_failure_backoff_and_recovery(self):
        probe=Mock(side_effect=[ValueError('offline'),ValueError('offline'),{'status':'reachable'}])
        health=AIHealth({'provider':'ollama'},interval=10,probe=probe,clock=lambda:100)
        health.check_once();self.assertEqual(health.state()['next_check_in_s'],10)
        health.check_once();self.assertEqual(health.state()['consecutive_failures'],2);self.assertEqual(health.state()['next_check_in_s'],20)
        health.check_once();self.assertEqual(health.state()['status'],'reachable');self.assertEqual(health.state()['consecutive_failures'],0)
    def test_backoff_is_bounded(self):
        health=AIHealth({},interval=15,probe=Mock(side_effect=ValueError('offline')))
        for _ in range(20):health.check_once()
        self.assertEqual(health.state()['check_interval_s'],300)
    def test_metadata_probe_does_not_run_inference(self):
        backend=Mock();backend.model='test';backend.endpoint='http://test'
        backend.request.return_value={'capabilities':['tools']}
        with patch('robot_platform.monitor.backend_from_settings',return_value=backend):result=probe_ai({'provider':'ollama'})
        self.assertEqual(result['status'],'reachable');backend.complete.assert_not_called()
        self.assertEqual(backend.request.call_args.kwargs['timeout'],5)
    def test_missing_model_or_tools_is_unavailable(self):
        backend=Mock();backend.request.return_value={'capabilities':['completion']}
        with patch('robot_platform.monitor.backend_from_settings',return_value=backend),self.assertRaises(ValueError):probe_ai({'provider':'ollama'})
    def test_no_ai_config_needed(self):
        self.assertEqual(probe_ai({})['status'],'not_configured')
    def test_events_only_on_status_changes(self):
        events=HealthEvents();state={'ai':{'status':'unavailable'},'robot':{'devices':{'BodyModule':{'health':'disconnected'}}}}
        self.assertEqual(len(events.update(state)),2);self.assertEqual(events.update(state),[])
        state['ai']['status']='reachable';self.assertEqual(events.update(state)[0]['previous'],'unavailable')
    def test_polling_continues_during_slow_ai_check_and_state_file_written(self):
        calls=[];progress=threading.Event();outputs=[]
        def read(devices):
            calls.append(1)
            if len(calls)>3:progress.set()
            return {'simulation':False,'devices':{'BodyModule':{'health':'ok'}}}
        def probe(settings):
            if not progress.wait(1):raise AssertionError('Hardware polling blocked')
            return {'status':'reachable'}
        with tempfile.TemporaryDirectory() as directory,patch('robot_platform.monitor.probe_ai',side_effect=probe):
            # Default callable is bound at definition; replace the factory argument explicitly.
            from robot_platform.monitor import AIHealth as RealHealth
            with patch('robot_platform.monitor.AIHealth',side_effect=lambda settings,interval:RealHealth(settings,interval,probe=probe)):
                path=Path(directory)/'state.json'
                watch({'ai_backend':{'provider':'ollama'}},{},read,outputs.append,interval=.05,ai_interval=1,ticks=5,state_file=path,save=save)
            self.assertEqual(json.loads(path.read_text())['ai']['status'],'reachable')
        self.assertGreater(len(calls),3);self.assertTrue(all(not output['actions_enabled'] for output in outputs))
    def test_serial_reconnect_clears_old_reading_and_emits_recovery(self):
        clock=[0];port=[Port()]
        driver=SerialTelemetry({'port':'test'},serial_factory=lambda *a,**k:port[0],clock=lambda:clock[0])
        driver.observe();port[0].data=b'{"type":"telemetry","protocol_version":1,"distance_cm":100,"strength":300,"valid":true,"sample_age_ms":0}\n'
        self.assertEqual(driver.observe()['health'],'ok')
        port[0].fail=True;self.assertEqual(driver.observe()['health'],'disconnected')
        clock[0]=3;port[0]=Port();state=driver.observe()
        self.assertEqual(state['health'],'waiting');self.assertIsNone(state['distance_m']);self.assertFalse(state['usable'])
        driver.close()
    def test_service_quotes_paths_and_never_uses_chat(self):
        with patch('robot_platform.service.platform.system',return_value='Linux'):
            content=unit('/tmp/robot config.json',['Body Module'],python='/tmp/virtual env/bin/python')
        self.assertIn('"/tmp/virtual env/bin/python"',content);self.assertIn('"watch"',content);self.assertNotIn('"chat"',content)
        self.assertIn('Restart=on-failure',content)
        self.assertEqual(quote('a%$b'),'"a%%$$b"')
        with self.assertRaises(ValueError):quote('x\nExecStart=bad')
    def test_service_generation_without_serial_or_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'robot.json';path.write_text(json.dumps({'schema_version':1,'devices':[{'name':'BodyModule','driver':'bb8-v2','port':'COM4'}]}))
            output=Path(directory)/'monitor.service'
            with patch('robot_platform.service.platform.system',return_value='Linux'),patch('robot_platform.bb8_bridge.BB8Bridge.__init__',side_effect=AssertionError('Opened serial')),redirect_stdout(StringIO()):
                self.assertEqual(main(['--config',str(path),'service','--device','BodyModule','--output',str(output)]),0)
                with self.assertRaises(SystemExit):main(['--config',str(path),'service','--output',str(output)])
            self.assertIn('BodyModule',output.read_text())
    def test_state_file_cannot_overwrite_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'robot.json';path.write_text(json.dumps({'schema_version':1,'devices':[]}));before=path.read_bytes()
            with self.assertRaises(SystemExit):main(['--config',str(path),'watch','--state-file',str(path)])
            self.assertEqual(path.read_bytes(),before)

    def test_sigterm_stops_watch_and_restores_handler(self):
        import signal
        previous=signal.getsignal(signal.SIGTERM)
        outputs=[]
        def emit(value):
            outputs.append(value)
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM,None)
        watch({}, {}, lambda devices:{'devices':{}}, emit, interval=.05)
        self.assertEqual(len(outputs),1)
        self.assertEqual(signal.getsignal(signal.SIGTERM),previous)
    def test_chat_starts_offline_and_exposes_health(self):
        from robot_platform.agent import chat
        backend=Mock();backend.model='test';backend.timeout_s=180
        backend.check.side_effect=ValueError('offline')
        health=Mock();health.state.return_value={'status':'unavailable'}
        output=StringIO()
        with patch('robot_platform.ai_backend.backend_from_settings',return_value=backend),patch('robot_platform.monitor.AIHealth',return_value=health),patch('builtins.input',side_effect=['/health','/quit']),redirect_stdout(output):
            chat({'ai_backend':{'provider':'ollama'}},{},lambda devices:{'devices':{}})
        self.assertIn('unavailable',output.getvalue());backend.check.assert_not_called();backend.complete.assert_not_called();health.close.assert_called_once()
