import json
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO
from robot_platform.bb8_bridge import BB8Bridge
from robot_platform.hardware import configure
from robot_platform.agent import Agent
from robot_platform.capabilities import report
from test_moods import MoodPort
from test_agent import Runtime


def telemetry(**changes):
    data={'type':'telemetry','dist':None,'sensor_valid':False,'head_connected':True,'strength':None,'sample_age_ms':None,'seq':1,'rx_overwrites':0,
          'light_supported':True,'illumination_supported':True,'light_raw':2048,'light_age_ms':5,'illumination_on':False}
    return {**data,**changes}

class LightTest(unittest.TestCase):
    def make(self,events=None,extensions=None):
        self.now=0;self.port=MoodPort(events or [])
        self.port.data=json.dumps(telemetry()).encode()+b'\n'
        self.driver=BB8Bridge({'port':'test','extensions':extensions if extensions is not None else ['ambient_light','illumination']},serial_factory=lambda *a,**k:self.port,clock=lambda:self.now)
        self.driver.sleep=lambda seconds:setattr(self,'now',self.now+seconds)
        return self.driver
    def test_light_freshness_independent_of_invalid_lidar(self):
        state=self.make().observe()
        self.assertFalse(state['usable']);self.assertTrue(state['light_usable']);self.assertEqual(state['light_percent'],50.0)
        self.now=.4;self.assertFalse(self.driver.observe()['light_usable'])
    def test_disabled_extensions_hide_reading_and_prevent_write(self):
        state=self.make(extensions=[]).observe();self.assertNotIn('light_raw',state);self.assertFalse(state['light_usable'])
        with self.assertRaises(ValueError):self.driver.command({'action':'illumination','on':True})
        self.assertEqual(self.port.writes,[])
    def test_matching_led_ack_only_and_one_write(self):
        driver=self.make([{'type':'command_sent','id':9,'accepted_by_radio':True},{'type':'illumination_ack','id':9,'on':True}])
        self.assertTrue(driver.command({'action':'illumination','on':True,'timeout':.2})['acknowledged'])
        self.assertEqual(self.port.writes,[b'illumination on\n'])
    def test_wrong_value_id_or_mood_ack_cannot_confirm_led(self):
        for event in [{'type':'illumination_ack','id':9,'on':False},{'type':'illumination_ack','id':10,'on':True},{'type':'command_ack','id':9,'mood':1}]:
            driver=self.make([{'type':'command_sent','id':9,'accepted_by_radio':True},event])
            self.assertEqual(driver.command({'action':'illumination','on':True,'timeout':.2})['status'],'ack_timeout')
            self.assertEqual(len(self.port.writes),1)
    def test_old_firmware_cannot_authorize_illumination(self):
        driver=self.make();data=telemetry()
        for key in ['light_supported','illumination_supported','light_raw','light_age_ms','illumination_on']:data.pop(key)
        self.port.data=json.dumps(data).encode()+b'\n'
        self.assertEqual(driver.command({'action':'illumination','on':True,'timeout':.2})['status'],'not_sent');self.assertEqual(self.port.writes,[])
    def test_malformed_light_frame_does_not_replace_last_good(self):
        driver=self.make();driver.observe()
        for changes in [{'light_raw':True},{'light_raw':4096},{'light_age_ms':-1},{'illumination_on':1}]:
            self.port.data=json.dumps(telemetry(**changes)).encode()+b'\n';state=driver.observe()
            self.assertEqual(state['light_raw'],2048)
        self.assertEqual(driver.malformed,4)
    def test_setup_selects_features_and_preserves_ai_connection(self):
        driver=self.make();config={'devices':[{'name':'BodyModule','driver':'bb8-v2','port':'test'}],'ai_backend':{'mode':'remote'}};saved=[]
        with patch('builtins.input',side_effect=['y','y','n','y']),redirect_stdout(StringIO()):
            configure('unused',config,lambda path,value:saved.append(value),'BodyModule',driver_factory=lambda c:driver)
        self.assertEqual(saved[0]['devices'][0]['extensions'],['ambient_light','illumination'])
        self.assertFalse(saved[0]['ai_capabilities']['devices']['BodyModule']['set_illumination']);self.assertEqual(saved[0]['ai_backend'],config['ai_backend']);self.assertNotIn('extensions',config['devices'][0])
    def test_capabilities_report_knows_configured_extensions_without_opening_port(self):
        config={'devices':[{'name':'BodyModule','driver':'bb8-v2','extensions':['illumination']}]}
        row=next(r for r in report(config,{'bb8-v2':BB8Bridge})['actions'] if r['action']=='set_illumination')
        self.assertTrue(row['devices'][0]['effective'])
    def test_ai_permission_and_output_turn_limit(self):
        runtime=Runtime();runtime.devices={'BodyModule':self.make()};runtime.illumination=lambda device,on:{'acknowledged':True}
        agent=Agent(None,runtime,trace=lambda x:None,permissions={'actions':{'set_illumination':False}})
        self.assertNotIn('set_illumination',[t['function']['name'] for t in agent.tools])
        self.assertIn('error',agent.execute('set_illumination',{'device':'BodyModule','on':True},[False]))
        agent=Agent(None,runtime,trace=lambda x:None);used=[False]
        self.assertTrue(agent.execute('set_illumination',{'device':'BodyModule','on':True},used)['acknowledged'])
        self.assertIn('error',agent.execute('set_buzzer_mood',{'device':'BodyModule','mood':'happy'},used))
