import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO
from robot_platform.capabilities import policy, allowed, set_permission, configure, report
from robot_platform.agent import Agent, tool_definitions
from robot_platform.cli import main
from robot_platform.drivers import SimMotor
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

    def test_motion_requires_explicit_global_and_per_device_permission(self):
        global_only={'actions':{'execute_motion':True}}
        self.assertFalse(allowed(global_only,'execute_motion','drive'))
        settings={
            'actions':{'execute_motion':True},
            'devices':{'drive':{'execute_motion':True}},
        }
        self.assertTrue(allowed(settings,'execute_motion','drive'))
        self.assertFalse(allowed(settings,'execute_motion','new-drive'))
        self.assertFalse(allowed(
            {'actions':{'execute_motion':False},'devices':{'drive':{'execute_motion':True}}},
            'execute_motion','drive',
        ))

    def test_invalid_policy_rejected(self):
        for value in [{'actions':{'run_shell':True}},{'actions':{'read_robot_state':'false'}},{'devices':[]}]:
            with self.assertRaises(ValueError):policy({'ai_capabilities':value})
    def test_configuration_is_not_mutated_by_edits_or_cancellation(self):
        original={'devices':[{'name':'BodyModule','driver':'bridge'}],'ai_backend':{'mode':'remote'}}
        changed=set_permission(original,'set_buzzer_mood',False,'BodyModule')
        self.assertNotIn('ai_capabilities',original);self.assertEqual(changed['ai_backend'],original['ai_backend'])
        with patch('builtins.input',side_effect=['n','n','n','n','n','n','n']),redirect_stdout(StringIO()):
            self.assertFalse(configure('unused',original,lambda *a:self.fail('Unexpected save'),{'bridge':Driver}))

    def test_interactive_motion_global_permission_defaults_no(self):
        config={'schema_version':1,'devices':[{'name':'drive','driver':'sim-motor'}]}
        saved=[]
        answers=['n','n','n','n','n','','y']
        with patch('builtins.input',side_effect=answers),redirect_stdout(StringIO()):
            self.assertTrue(configure('unused',config,lambda path,value:saved.append(value),{'sim-motor':SimMotor}))
        self.assertFalse(saved[0]['ai_capabilities']['actions']['execute_motion'])

    def test_interactive_motion_device_permission_defaults_no(self):
        config={'schema_version':1,'devices':[{'name':'drive','driver':'sim-motor'}]}
        saved=[]
        answers=['n','n','n','n','n','y','','y']
        with patch('builtins.input',side_effect=answers),redirect_stdout(StringIO()):
            self.assertTrue(configure('unused',config,lambda path,value:saved.append(value),{'sim-motor':SimMotor}))
        permissions=saved[0]['ai_capabilities']
        self.assertTrue(permissions['actions']['execute_motion'])
        self.assertFalse(permissions['devices']['drive']['execute_motion'])
    def test_cli_disable_persists_without_opening_devices(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'robot.json';path.write_text(json.dumps({'schema_version':1,'devices':[{'name':'BodyModule','driver':'bb8-v2','port':'COM4'}]}))
            with patch('robot_platform.bb8_bridge.BB8Bridge.__init__',side_effect=AssertionError('Opened serial')),redirect_stdout(StringIO()):
                self.assertEqual(main(['--config',str(path),'capabilities','disable','set_buzzer_mood','--device','BodyModule']),0)
            self.assertFalse(json.loads(path.read_text())['ai_capabilities']['devices']['BodyModule']['set_buzzer_mood'])

    def test_cli_device_motion_enable_sets_both_required_gates(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'robot.json'
            path.write_text(json.dumps({
                'schema_version':1,
                'devices':[{'name':'drive','kind':'motor','driver':'sim-motor'}],
            }))
            with redirect_stdout(StringIO()):
                self.assertEqual(main([
                    '--config',str(path),'capabilities','enable','execute_motion',
                    '--device','drive',
                ]),0)
            config=json.loads(path.read_text())
            permissions=config['ai_capabilities']
            self.assertTrue(permissions['actions']['execute_motion'])
            self.assertTrue(permissions['devices']['drive']['execute_motion'])
            runtime=SimpleNamespace(devices={'drive':SimMotor({'name':'drive'})})
            agent=Agent(None,runtime,permissions=policy(config))
            self.assertIn('execute_motion',[tool['function']['name'] for tool in agent.tools])

    def test_cli_global_motion_enable_does_not_grant_a_device(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'robot.json'
            path.write_text(json.dumps({
                'schema_version':1,
                'devices':[{'name':'drive','kind':'motor','driver':'sim-motor'}],
            }))
            with redirect_stdout(StringIO()):
                self.assertEqual(main([
                    '--config',str(path),'capabilities','enable','execute_motion',
                ]),0)
            config=json.loads(path.read_text())
            self.assertTrue(config['ai_capabilities']['actions']['execute_motion'])
            runtime=SimpleNamespace(devices={'drive':SimMotor({'name':'drive'})})
            agent=Agent(None,runtime,permissions=policy(config))
            self.assertNotIn('execute_motion',[tool['function']['name'] for tool in agent.tools])

    def test_unsupported_device_cannot_become_buzzer_capable(self):
        runtime=Runtime();runtime.devices={'range':object()}
        agent=Agent(None,runtime,permissions={'devices':{'range':{'set_buzzer_mood':True}}})
        self.assertEqual(len(agent.tools),1)
        self.assertIn('error',agent.execute('set_buzzer_mood',{'device':'range','mood':'happy'},[False]))

    def test_target_selection_is_explicit_and_capability_gated(self):
        class Vision:
            kind='sensor';capabilities={'target_selection':True}
        runtime=Runtime();runtime.devices={'Vision':Vision()}
        self.assertNotIn('select_target',[t['function']['name'] for t in Agent(None,runtime).tools])
        enabled=Agent(None,runtime,permissions={'actions':{'select_target':True}})
        self.assertIn('select_target',[t['function']['name'] for t in enabled.tools])
        unsupported=Runtime();unsupported.devices={'range':object()}
        self.assertNotIn('select_target',[t['function']['name'] for t in Agent(None,unsupported,permissions={'actions':{'select_target':True}}).tools])
        self.assertFalse(allowed({},'select_target','Vision'))
        self.assertTrue(allowed({'actions':{'select_target':True}},'select_target','Vision'))
        class MotorVision:
            kind='motor';capabilities={'target_selection':True}
        motor=Runtime();motor.devices={'unsafe':MotorVision()}
        self.assertNotIn('select_target',[t['function']['name'] for t in Agent(None,motor,permissions={'actions':{'select_target':True}}).tools])
