import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO
from robot_platform.agent import Agent,RobotRuntime,tool_definitions
from robot_platform.ollama_backend import OllamaBackend,local_endpoint,configure_ai

class Driver:
    capabilities={'mood':{'values':['happy']}}
    def command(self,action):return {'acknowledged':True}
class Runtime:
    devices={'BodyModule':Driver()}
    def __init__(self):self.moods=[];self.reads=0
    def state(self):
        self.reads+=1
        return {'simulation':False,'devices':{'BodyModule':{'health':'ok','observation':{'distance_m':1.61,'usable':True}}}}
    def mood(self,device,mood):self.moods.append((device,mood));return {'acknowledged':True,'mood':mood}
class Backend:
    def __init__(self,responses):self.responses=iter(responses);self.requests=[]
    def complete(self,messages,tools):self.requests.append(list(messages));return next(self.responses)
def call(name,args):return {'function':{'name':name,'arguments':args}}
def message(*calls,content=''):return {'role':'assistant','content':content,'tool_calls':list(calls)}

class AgentTest(unittest.TestCase):
    def test_state_tool_and_final_model_reply(self):
        runtime=Runtime();backend=Backend([message(call('read_robot_state',{})),message(content='The beam distance is 1.61 m.')])
        agent=Agent(backend,runtime,trace=lambda x:None)
        self.assertEqual(agent.turn('How far away?'),'The beam distance is 1.61 m.')
        self.assertEqual(runtime.reads,1)
        result=json.loads(backend.requests[1][-1]['content'])
        self.assertEqual(result['devices']['BodyModule']['observation']['distance_m'],1.61)
    def test_mood_only_once_even_if_model_repeats(self):
        runtime=Runtime();backend=Backend([message(call('set_buzzer_mood',{'device':'BodyModule','mood':'happy'}),call('set_buzzer_mood',{'device':'BodyModule','mood':'happy'})),message(content='Head acknowledged happy.')])
        traces=[];agent=Agent(backend,runtime,trace=traces.append)
        agent.turn('Make a happy sound')
        self.assertEqual(runtime.moods,[('BodyModule','happy')])
        self.assertTrue(any('[buzzer]' in value for value in traces))
    def test_unknown_and_invalid_tools_do_not_execute(self):
        runtime=Runtime();agent=Agent(None,runtime,trace=lambda x:None)
        for name,args in [('run_shell',{'cmd':'x'}),('set_buzzer_mood',{'device':'Other','mood':'happy'}),
                         ('set_buzzer_mood',{'device':'BodyModule','mood':'happy','extra':1}),
                         ('read_robot_state',{'ignored':True}),('set_buzzer_mood','{bad')]:
            self.assertIn('error',agent.execute(name,args,[False]))
        self.assertEqual(runtime.moods,[])
        self.assertEqual(runtime.reads,0)
    def test_read_only_device_has_no_mood_tool(self):
        runtime=Runtime();runtime.devices={'range':object()}
        self.assertEqual(len(tool_definitions(runtime)),1)
    def test_tool_loop_bound(self):
        runtime=Runtime();agent=Agent(Backend([message(call('read_robot_state',{}))]*5),runtime,trace=lambda x:None)
        with self.assertRaises(ValueError):agent.turn('Read distance')
        self.assertEqual(runtime.reads,4)
    def test_polling_continues_while_backend_waits(self):
        count=[0];progress=threading.Event()
        def snapshot(devices):
            count[0]+=1
            if count[0]>=3:progress.set()
            return {'devices':{}}
        runtime=RobotRuntime({},snapshot)
        class SlowBackend:
            def complete(self,messages,tools):
                if not progress.wait(2):raise ValueError('Polling stopped')
                return message(content='Ready')
        runtime.start()
        try:self.assertEqual(Agent(SlowBackend(),runtime).turn('Hello'),'Ready')
        finally:runtime.close()
        self.assertGreaterEqual(count[0],3)
        self.assertFalse(runtime.worker.is_alive())
    def test_setup_cancellation_preserves_config(self):
        config={'schema_version':1,'devices':[]}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'robot.json';path.write_text(json.dumps(config))
            before=path.read_bytes()
            with patch.object(OllamaBackend,'check',return_value={'provider':'ollama'}),patch('builtins.input',return_value='n'),redirect_stdout(StringIO()):
                self.assertFalse(configure_ai(path,config,lambda *a:self.fail('Unexpected save'),'http://localhost:11434','qwen3:4b'))
            self.assertEqual(path.read_bytes(),before)
    def test_remote_endpoints_and_cloud_models_rejected(self):
        for value in ['http://example.com','http://localhost:11434/path','http://user@localhost:11434']:
            with self.assertRaises(ValueError):local_endpoint(value)
        with self.assertRaises(ValueError):OllamaBackend(model='x:cloud').check()
    def test_whole_turn_history_is_bounded(self):
        agent=Agent(Backend([message(content='Hello')]*8),Runtime(),trace=lambda x:None)
        for i in range(8):agent.turn('Hello')
        self.assertEqual(len(agent.history),6)
        self.assertTrue(all(turn[0]['role']=='user' for turn in agent.history))
    def test_ollama_http_tool_roundtrip(self):
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append((self.path,payload))
                if self.path=='/api/show':result={'capabilities':['tools','completion']}
                else:
                    is_result=payload['messages'][-1]['role']=='tool'
                    result={'message':message(content='The beam distance is 1.61 m.') if is_result else message(call('read_robot_state',{}))}
                data=json.dumps(result).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever);thread.start()
        try:
            backend=OllamaBackend(f'http://127.0.0.1:{server.server_port}','test-model')
            self.assertTrue(backend.check()['tool_support'])
            result=Agent(backend,Runtime(),trace=lambda x:None).turn('Distance?')
            self.assertIn('1.61',result)
            self.assertEqual([path for path,payload in requests],['/api/show','/api/chat','/api/chat'])
            self.assertFalse(requests[1][1]['stream'])
        finally:server.shutdown();thread.join();server.server_close()
