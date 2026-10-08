import json
import unittest
from unittest.mock import patch
from robot_platform.discovery import validate_manifest, discover
from robot_platform.demo import discovery_demo, VirtualPort
from robot_platform.serial_driver import SerialTelemetry
from robot_platform.setup import apply_discovery

def hello(**changes):
    return {'type':'hello','protocol_version':1,'controller_id':'body-1','name':'Body',
            'firmware_version':'0.4','capabilities':[
                {'id':'range','kind':'sensor','driver':'tfmini-plus','units':'m'},
                {'id':'ring','kind':'output','driver':'neopixel','units':'rgb'}], **changes}

class DiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.now=0
        self.port=VirtualPort()
        self.driver=SerialTelemetry({'port':'virtual'},serial_factory=lambda *a,**k:self.port,clock=lambda:self.now)
    def send(self,data):
        self.port.data+=json.dumps(data).encode()+b'\n'
        return self.driver.observe()
    def test_hello_does_not_refresh_sensor(self):
        self.send({'type':'telemetry','protocol_version':1,'distance_cm':100,'valid':True,'sample_age_ms':0})
        self.now=2
        state=self.send(hello())
        self.assertEqual(state['health'],'stale')
        self.assertEqual(state['received_age_s'],2)
        self.assertEqual(state['controller']['controller_id'],'body-1')
        self.assertFalse(state['controller']['capabilities'][1]['host_supported'])
        self.assertFalse(state['controller']['capabilities'][1]['commands_enabled'])
    def test_malformed_manifest_and_reconnect(self):
        for changes in [{'protocol_version':True},{'controller_id':''},{'capabilities':[{},{}]},
                        {'capabilities':hello()['capabilities']*2}]:
            with self.assertRaises(ValueError): validate_manifest(hello(**changes))
        self.send(hello())
        self.port.unplugged=True
        self.driver.observe()
        self.now=3
        self.port=VirtualPort()
        self.assertIsNone(self.driver.observe()['controller'])
    def test_disabled_capability_and_wrong_controller(self):
        self.driver.config.update(controller={'controller_id':'other'},enabled_capabilities=['range'])
        self.send(hello())
        reading={'type':'telemetry','protocol_version':1,'distance_cm':100,'valid':True,'sample_age_ms':0}
        self.assertEqual(self.send(reading)['health'],'identity_mismatch')
        self.assertFalse(self.send(reading)['usable'])
        self.driver.config['controller']={'controller_id':'body-1'}
        self.driver.config['enabled_capabilities']=[]
        self.assertEqual(self.send(reading)['health'],'disabled')
    def test_discovery_closes_transport(self):
        self.port.data=json.dumps(hello()).encode()+b'\n'
        result=discover({'port':'virtual'},driver_factory=lambda config:self.driver)
        self.assertTrue(result['discovered'])
        self.assertFalse(self.port.is_open)
    def test_setup_only_enables_supported_capabilities(self):
        with patch('builtins.input',side_effect=['y']):
            device=apply_discovery({},validate_manifest(hello()))
        self.assertEqual(device['enabled_capabilities'],['range'])
    def test_demo_is_simulation(self):
        result=discovery_demo()
        self.assertTrue(result['simulation'])
        self.assertTrue(result['discovered'])
        self.assertFalse(result['controller']['capabilities'][1]['host_supported'])
    def test_duplicate_port_is_rejected(self):
        from robot_platform.setup import check_connection_unique
        with patch('robot_platform.setup.os.name','nt'):
            with self.assertRaises(ValueError):
                check_connection_unique([{'name':'existing','port':'COM05'}],{'port':'5'})
    def test_link_invalid_even_with_valid_sample(self):
        state=self.send({'type':'telemetry','protocol_version':1,'distance_cm':100,
                         'valid':True,'sample_age_ms':0,'head_link_valid':False,'sample_sequence':5})
        self.assertEqual(state['health'],'invalid')
        self.assertFalse(state['usable'])
        self.assertEqual(state['sample_sequence'],5)
    def test_multiple_supported_channels_rejected(self):
        capability=dict(hello()['capabilities'][0],id='range2')
        with self.assertRaises(ValueError):
            validate_manifest(hello(capabilities=[hello()['capabilities'][0],capability]))
    def test_cli_demo_and_hardware_save_block(self):
        from robot_platform.cli import main
        from contextlib import redirect_stdout, redirect_stderr
        from io import StringIO
        with redirect_stdout(StringIO()) as output:
            self.assertEqual(main(['discover','--demo']),0)
        self.assertTrue(json.loads(output.getvalue())['simulation'])
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            main(['discover','--demo','--save-as','fake'])
