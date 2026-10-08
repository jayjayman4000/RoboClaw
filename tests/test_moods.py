import json
import unittest
from robot_platform.bb8_bridge import BB8Bridge
from robot_platform.demo import VirtualPort

class MoodPort(VirtualPort):
    def __init__(self,events):
        super().__init__();self.events=events;self.writes=[]
        self.data=json.dumps({'type':'telemetry','dist':None,'sensor_valid':False,'head_connected':True,
                              'strength':None,'sample_age_ms':None,'seq':1,'rx_overwrites':0}).encode()+b'\n'
    def write(self,payload):
        self.writes.append(payload)
        self.data+=b''.join(json.dumps(e).encode()+b'\n' for e in self.events)
        return len(payload)

class MoodTest(unittest.TestCase):
    def make(self,events):
        self.now=0
        self.port=MoodPort(events)
        self.driver=BB8Bridge({'port':'virtual'},serial_factory=lambda *a,**k:self.port,clock=lambda:self.now)
        self.driver.sleep=lambda seconds:setattr(self,'now',self.now+seconds)
        return self.driver
    def request(self): return self.driver.command({'action':'mood','mood':'happy','timeout':.2})
    def test_matching_ack_and_invalid_lidar_allowed(self):
        self.make([{'type':'command_sent','id':7,'accepted_by_radio':True},{'type':'command_ack','id':7,'mood':1}])
        result=self.request()
        self.assertTrue(result['acknowledged'])
        self.assertEqual(result['command_id'],7)
        self.assertEqual(self.port.writes,[b'happy\n'])
    def test_wrong_id_or_mood_cannot_confirm(self):
        for ack in [{'id':8,'mood':1},{'id':7,'mood':2}]:
            self.make([{'type':'command_sent','id':7,'accepted_by_radio':True},{'type':'command_ack',**ack}])
            self.assertEqual(self.request()['status'],'ack_timeout')
            self.assertEqual(len(self.port.writes),1)
    def test_radio_rejection_and_firmware_error(self):
        self.make([{'type':'command_sent','id':7,'accepted_by_radio':False}])
        self.assertEqual(self.request()['status'],'radio_rejected')
        self.make([{'type':'error','error':'head_not_paired'}])
        self.assertEqual(self.request()['status'],'rejected')
    def test_no_head_no_write(self):
        self.make([]);self.port.data=b''
        self.assertEqual(self.request()['status'],'not_sent')
        self.assertEqual(self.port.writes,[])
    def test_unrecognized_action_never_writes(self):
        self.make([])
        with self.assertRaises(ValueError):self.driver.command({'action':'set_speed','value':1})
        self.assertEqual(self.port.writes,[])
    def test_prior_ack_not_reused(self):
        self.make([{'type':'command_sent','id':7,'accepted_by_radio':True}])
        self.port.data+=b'{"type":"command_ack","id":7,"mood":1}\n'
        self.assertEqual(self.request()['status'],'ack_timeout')
    def test_legacy_telemetry_cannot_authorize_write(self):
        self.make([]);self.port.data=b'{"type":"telemetry","dist":100}\n'
        self.assertEqual(self.request()['status'],'not_sent')
        self.assertEqual(self.port.writes,[])
