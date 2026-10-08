import json
import unittest
from robot_platform.serial_driver import SerialTelemetry
from robot_platform.demo import VirtualPort

class BB8V2Test(unittest.TestCase):
    def setUp(self):
        self.now=0
        self.port=VirtualPort()
        self.driver=SerialTelemetry({'port':'test'},serial_factory=lambda *a,**k:self.port,clock=lambda:self.now)
    def send(self,**changes):
        frame={'type':'telemetry','dist':161,'brake':False,'sensor_valid':True,
               'head_connected':True,'strength':1490,'sample_age_ms':46,'seq':11519,'rx_overwrites':81}
        frame.update(changes)
        self.port.data+=json.dumps(frame).encode()+b'\n'
        return self.driver.observe()
    def test_real_frame(self):
        state=self.send()
        self.assertEqual(state['telemetry_schema'],'bb8-v2')
        self.assertEqual(state['health'],'ok')
        self.assertTrue(state['usable'])
        self.assertEqual(state['distance_m'],1.61)
        self.assertEqual(state['strength'],1490)
        self.assertEqual(state['sample_sequence'],11519)
        self.assertEqual(state['rx_overwrites'],81)
    def test_nulls_on_invalid_and_link_loss(self):
        state=self.send(dist=None,sensor_valid=False,strength=None,sample_age_ms=None,brake=True)
        self.assertEqual(state['health'],'invalid')
        self.assertFalse(state['usable'])
        self.assertIsNone(state['distance_m'])
        state=self.send(dist=None,sensor_valid=False,head_connected=False,strength=None,sample_age_ms=None,brake=True)
        self.assertEqual(state['health'],'head_disconnected')
        self.assertEqual(state['malformed_lines'],0)
    def test_sensor_and_host_age_are_combined(self):
        self.send(sample_age_ms=300)
        self.now=.06
        state=self.driver.observe()
        self.assertEqual(state['health'],'stale')
        self.assertFalse(state['usable'])
    def test_bad_or_partial_health_fields_rejected(self):
        for changes in [{'sensor_valid':'true'},{'head_connected':1},{'seq':True},
                        {'rx_overwrites':-1},{'sample_age_ms':None},{'head_connected':False}]:
            state=self.send(**changes)
            self.assertFalse(state['usable'])
        self.assertEqual(self.driver.malformed,6)
    def test_invalid_strength_cannot_be_usable(self):
        for strength in [0,99,65535,None]:
            self.assertFalse(self.send(strength=strength)['usable'])
    def test_reconnect_accepts_reset_sequence(self):
        self.send()
        self.port.unplugged=True
        self.assertEqual(self.driver.observe()['health'],'disconnected')
        self.now=3
        self.port=VirtualPort()
        self.assertIsNone(self.driver.observe()['distance_m'])
        self.assertTrue(self.send(seq=1)['usable'])
    def test_fresh_connection_test_waits_for_usable(self):
        from unittest.mock import patch, MagicMock
        from robot_platform.serial_driver import connection_test
        driver=MagicMock()
        driver.observe.side_effect=[{'received_at':'now','usable':False},{'received_at':'now','usable':True}]
        with patch('robot_platform.serial_driver.SerialTelemetry',return_value=driver), \
             patch('robot_platform.serial_driver.time.monotonic',side_effect=[0,0,.1]), \
             patch('robot_platform.serial_driver.time.sleep'):
            result=connection_test({'port':'test'},timeout=.2,require_fresh=True)
        self.assertTrue(result['passed'])
        self.assertEqual(driver.observe.call_count,2)
        driver.close.assert_called_once()
    def test_fresh_connection_test_rejects_invalid_only(self):
        from unittest.mock import patch, MagicMock
        from robot_platform.serial_driver import connection_test
        driver=MagicMock()
        driver.observe.return_value={'received_at':'now','usable':False}
        with patch('robot_platform.serial_driver.SerialTelemetry',return_value=driver), \
             patch('robot_platform.serial_driver.time.monotonic',side_effect=[0,0,.3]), \
             patch('robot_platform.serial_driver.time.sleep'):
            self.assertFalse(connection_test({'port':'test'},timeout=.2,require_fresh=True)['passed'])
        driver.close.assert_called_once()
    def test_selected_stream_does_not_open_other_devices(self):
        import tempfile
        from pathlib import Path
        from contextlib import redirect_stdout
        from io import StringIO
        from unittest.mock import patch
        from robot_platform.cli import main,save
        opened=[]
        class Spy:
            fields={}
            def __init__(self,config): opened.append(config['name'])
            def observe(self): return {'health':'ok'}
            def close(self): pass
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'robot.json'
            save(path,{'schema_version':1,'devices':[{'name':n,'driver':'spy'} for n in ['BodyModule','HeadModule','camera']]})
            with patch('robot_platform.cli.registry',return_value={'spy':Spy}),redirect_stdout(StringIO()) as output:
                self.assertEqual(main(['--config',str(path),'run','--device','BodyModule','--ticks','1']),0)
            self.assertEqual(opened,['BodyModule'])
            self.assertEqual(set(json.loads(output.getvalue())['devices']),{'BodyModule'})
