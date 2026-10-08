import json
import os
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO
from robot_platform.ai_backend import APIBackend, backend_from_settings, configure_ai, doctor
from robot_platform.ollama_backend import OllamaBackend
from robot_platform.agent import Agent
from test_agent import Runtime, message

class AIBackendTest(unittest.TestCase):
    def test_remote_opt_in_and_persistence(self):
        with self.assertRaises(ValueError):OllamaBackend('http://100.111.212.1:11434')
        backend=backend_from_settings({'provider':'ollama','mode':'remote','endpoint':'http://100.111.212.1:11434','model':'test'})
        with patch.object(backend,'request',return_value={'capabilities':['tools']}):
            self.assertEqual(backend.check()['mode'],'remote')
        for endpoint in ['http://user:secret@100.111.212.1','http://100.111.212.1/path','http://100.111.212.1:bad']:
            with self.assertRaises(ValueError):OllamaBackend(endpoint,remote=True)
    def test_api_endpoint_and_key_validation(self):
        for endpoint in ['http://example.com/v1','https://user:key@example.com/v1']:
            with self.assertRaises(ValueError):APIBackend(endpoint,'test')
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaisesRegex(ValueError,'OPENAI_API_KEY'):APIBackend('https://example.com/v1','test').check()
    def test_hosted_tool_roundtrip(self):
        backend=APIBackend('https://example.com/v1','test')
        responses=[{'choices':[{'message':{'role':'assistant','content':None,'tool_calls':[{'id':'call_1','type':'function','function':{'name':'read_robot_state','arguments':'{}'}}]}}]},
                   {'choices':[{'message':message(content='Distance is 1.61 m.')}]}]
        with patch.object(backend,'request',side_effect=responses) as request:
            self.assertIn('1.61',Agent(backend,Runtime(),trace=lambda x:None).turn('Distance?'))
        payload=request.call_args.args[1]
        self.assertEqual(payload['messages'][-1]['tool_call_id'],'call_1')
        self.assertNotIn('tool_name',payload['messages'][-1])
    def test_setup_saves_remote_and_preserves_devices(self):
        saved=[];config={'devices':[{'name':'BodyModule'}]}
        with patch.object(OllamaBackend,'check',return_value={'provider':'ollama','mode':'remote'}),patch('builtins.input',return_value='y'),redirect_stdout(StringIO()):
            self.assertTrue(configure_ai('unused',config,lambda p,c:saved.append(c),'http://100.111.212.1:11434','test',mode='remote'))
        self.assertEqual(saved[0]['devices'],config['devices'])
        self.assertEqual(saved[0]['ai_backend']['mode'],'remote')
    def test_api_setup_probe_never_dispatches_hardware_or_saves_key(self):
        saved=[]
        result={'role':'assistant','content':'','tool_calls':[{'id':'probe','function':{'name':'connection_probe','arguments':'{}'}}]}
        with patch.dict(os.environ,{'OPENAI_API_KEY':'secret-value'}),patch.object(APIBackend,'complete',return_value=result),patch('builtins.input',side_effect=['OPENAI_API_KEY','y']),redirect_stdout(StringIO()):
            self.assertTrue(configure_ai('unused',{},lambda p,c:saved.append(c),'https://example.com/v1','test',mode='api'))
        self.assertNotIn('secret-value',json.dumps(saved))
        self.assertTrue(saved[0]['ai_backend']['tool_support'])
    def test_doctor_reports_failure_stage_without_inference(self):
        with patch('socket.getaddrinfo',return_value=[(0,0,0,'',('100.111.212.1',11434))]),patch('socket.create_connection',side_effect=TimeoutError('timed out')),patch.object(OllamaBackend,'complete') as complete:
            report=doctor({},'http://100.111.212.1:11434','remote')
        self.assertFalse(report['ok']);self.assertEqual(report['checks'][-1]['stage'],'tcp');complete.assert_not_called()
    def test_doctor_http_success(self):
        with patch('socket.getaddrinfo',return_value=[(0,0,0,'',('127.0.0.1',11434))]),patch('socket.create_connection'),patch.object(OllamaBackend,'request',side_effect=[{'version':'test'},{'models':[{'name':'test-model'}]}]):
            report=doctor({},'http://localhost:11434','local')
        self.assertTrue(report['ok']);self.assertEqual(report['models'],['test-model'])
