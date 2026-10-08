"""Read-only runtime monitoring; network checks never dispatch hardware commands."""
import math
import signal
import threading
import time
from datetime import datetime, timezone
from .ai_backend import backend_from_settings
from .agent import RobotRuntime


def utc_now():return datetime.now(timezone.utc).isoformat()


def probe_ai(settings):
    if not settings.get('provider'):
        return {'status':'not_configured','inference_tested':False}
    backend = backend_from_settings(settings)
    if settings['provider'] == 'ollama':
        metadata = backend.request('/api/show',{'model':backend.model},timeout=5)
        if metadata.get('remote_host') or metadata.get('remote_model'):
            raise ValueError('Configured Ollama model uses cloud inference; select a downloaded model')
        if 'tools' not in metadata.get('capabilities',[]):
            raise ValueError('Configured model does not report tool support')
    else:
        values = backend.request('/models',timeout=5).get('data')
        if not isinstance(values,list):raise ValueError('Invalid hosted model list')
        if backend.model not in [m.get('id') for m in values if isinstance(m,dict)]:
            raise ValueError('Configured model is absent from the hosted model list')
    return {'status':'reachable','provider':settings['provider'],'endpoint':backend.endpoint,
            'model':backend.model,'inference_tested':False}


class AIHealth:
    def __init__(self,settings,interval=15,probe=probe_ai,clock=time.monotonic):
        if not math.isfinite(interval) or not 1 <= interval <= 300:raise ValueError('AI check interval must be between 1 and 300 seconds')
        self.settings,self.interval,self.probe,self.clock=settings,interval,probe,clock
        self.lock=threading.Lock();self.stop=threading.Event();self.worker=None
        self.value={'status':'checking' if settings.get('provider') else 'not_configured','checked_at':None,'consecutive_failures':0,'inference_tested':False}
        self.next_check=0

    def check_once(self):
        try:
            result=self.probe(self.settings)
            failures=0;delay=self.interval
        except Exception as error:
            with self.lock:failures=self.value['consecutive_failures']+1
            delay=min(300,self.interval * 2 ** min(failures-1,5))
            result={'status':'unavailable','error':str(error),'inference_tested':False}
        with self.lock:
            self.next_check=self.clock()+delay
            self.value={**result,'checked_at':utc_now(),'consecutive_failures':failures,'check_interval_s':delay}

    def state(self):
        with self.lock:return {**self.value,'next_check_in_s':max(0,round(self.next_check-self.clock(),2)) if self.value['checked_at'] else None}

    def start(self):
        def loop():
            while not self.stop.is_set():
                self.check_once()
                if self.stop.wait(max(0,self.next_check-self.clock())):break
        self.worker=threading.Thread(target=loop,name='roboclaw-ai-health',daemon=True)
        self.worker.start()

    def close(self):
        self.stop.set()
        if self.worker:self.worker.join(timeout=1)


class HealthEvents:
    def __init__(self):self.previous={}
    def update(self,state):
        current={'ai':state['ai']['status']}
        current.update({'device:'+name:value['health'] for name,value in state['robot']['devices'].items()})
        events=[]
        for component,status in current.items():
            previous=self.previous.get(component)
            if previous != status:events.append({'component':component,'previous':previous,'status':status})
        self.previous=current
        return events


def watch(config,devices,snapshot,emit,interval=1,ai_interval=15,ticks=0,state_file=None,save=None):
    if ticks<0 or not math.isfinite(interval) or not .05<=interval<=60:raise ValueError('ticks must be >= 0; interval must be between 0.05 and 60 seconds')
    runtime=RobotRuntime(devices,snapshot)
    ai=AIHealth(config.get('ai_backend',{}),ai_interval)
    events=HealthEvents();stop=threading.Event();previous=None
    if threading.current_thread() is threading.main_thread():
        previous=signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM,lambda *_:stop.set())
    try:
        runtime.start();ai.start();count=0
        while not stop.is_set() and (ticks==0 or count<ticks):
            state={'schema_version':1,'observed_at':utc_now(),'mode':'monitor','actions_enabled':False,
                   'robot':runtime.state(),'ai':ai.state()}
            state['events']=events.update(state)
            if state_file is not None:save(state_file,state)
            emit(state);count+=1
            if ticks and count>=ticks:break
            stop.wait(interval)
    except KeyboardInterrupt:pass
    finally:
        stop.set();ai.close();runtime.close()
        if previous is not None:signal.signal(signal.SIGTERM,previous)
