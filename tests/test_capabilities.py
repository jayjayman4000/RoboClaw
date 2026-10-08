import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO
from robot_platform.capabilities import policy, allowed, set_permission, configure, report
from robot_platform.agent import Agent, tool_definitions
from robot_platform.cli import main
from test_agent import Runtime, Driver

class CapabilityTest(unittest.TestCase):
    def test_defaults_preserve_existing_tools(self):
        self.assertEqual(len(tool_definitions(Runtime())),2)
    def test_disabled_buzzer_hidden_and_forged_call_blocked(self):
        runtime=Runtime();agent=Agent(None,runtime,trace=lambda x:None,permissions={'actions':{'set_buzzer_mood':False}})
        self.assertEqual([t['function']['name'] for t in agent.tools],['read_robot_state'])
        self.assertIn('error',agent.execute('set_buzzer_mood',{'device':'BodyModule','mood':'happy'},[False]))
        self.assertEqual(runtime.moods,[])
    def test_disabled_sensor_never_reads(self):
        runtime=Runtime();agent=Agent(None,runtime,permissions={'actions':{'read_robot_state':False}})
        self.assertIn('error',agent.execute('read_robot_state',{},[False]));self.assertEqual(runtime.reads,0)
    def test_per_device_filters_sensor_results_and_buzzer_enum(self):
        runtime=Runtime();runtime.devices={'BodyModule':Driver(),'Private':Driver()}
        agent=Agent(None,runtime,permissions={'devices':{'BodyModule':{'read_robot_state':False},'Private':{'set_buzzer_mood':False}}})
        result=agent.execute('read_robot_state',{},[False]);self.assertNotIn('BodyModule',result['devices'])
        tool=next(t for t in agent.tools if t['function']['name']=='set_buzzer_mood')
        self.assertEqual(tool['function']['parameters']['properties']['device']['enum'],['BodyModule'])
        self.assertIn('error',agent.execute('set_buzzer_mood',{'device':'Private','mood':'happy'},[False]));self.assertEqual(runtime.moods,[])
    def test_global_disable_wins_over_device_enable(self):
        self.assertFalse(allowed({'actions':{'set_buzzer_mood':False},'devices':{'BodyModule':{'set_buzzer_mood':True}}},'set_buzzer_mood','BodyModule'))
    def test_invalid_policy_rejected(self):
        for value in [{'actions':{'run_shell':True}},{'actions':{'read_robot_state':'false'}},{'devices':[]}]:
            with self.assertRaises(ValueError):policy({'ai_capabilities':value})
    def test_configuration_is_not_mutated_by_edits_or_cancellation(self):
        original={'devices':[{'name':'BodyModule','driver':'bridge'}],'ai_backend':{'mode':'remote'}}
        changed=set_permission(original,'set_buzzer_mood',False,'BodyModule')
        self.assertNotIn('ai_capabilities',original);self.assertEqual(changed['ai_backend'],original['ai_backend'])
        with patch('builtins.input',side_effect=['n','n','n','n']),redirect_stdout(StringIO()):
            self.assertFalse(configure('unused',original,lambda *a:self.fail('Unexpected save'),{'bridge':Driver}))
    def test_cli_disable_persists_without_opening_devices(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'robot.json';path.write_text(json.dumps({'schema_version':1,'devices':[{'name':'BodyModule','driver':'bb8-v2','port':'COM4'}]}))
            with patch('robot_platform.bb8_bridge.BB8Bridge.__init__',side_effect=AssertionError('Opened serial')),redirect_stdout(StringIO()):
                self.assertEqual(main(['--config',str(path),'capabilities','disable','set_buzzer_mood','--device','BodyModule']),0)
            self.assertFalse(json.loads(path.read_text())['ai_capabilities']['devices']['BodyModule']['set_buzzer_mood'])
    def test_unsupported_device_cannot_become_buzzer_capable(self):
        runtime=Runtime();runtime.devices={'range':object()}
        agent=Agent(None,runtime,permissions={'devices':{'range':{'set_buzzer_mood':True}}})
        self.assertEqual(len(agent.tools),1)
        self.assertIn('error',agent.execute('set_buzzer_mood',{'device':'range','mood':'happy'},[False]))
