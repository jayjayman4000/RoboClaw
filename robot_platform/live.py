"""One hardware owner for prompt-free local observation and reaction."""
import math
import signal
import threading
from .agent import RobotRuntime
from .behaviors import settings as behavior_settings
from .reactions import settings as reaction_settings


def run_live(config, devices, snapshot, emit, interval=1, ticks=0):
    if type(interval) not in (int, float) or not math.isfinite(interval) or not .1 <= interval <= 60:
        raise ValueError('Live interval must be 0.1–60 seconds')
    if type(ticks) is not int or ticks < 0:raise ValueError('ticks must be >= 0')
    if not devices:raise ValueError('Select at least one enabled hardware device')
    runtime = RobotRuntime(devices, snapshot, behavior_settings(config), reaction_settings(config))
    stopped = threading.Event()
    previous = None
    if threading.current_thread() is threading.main_thread():
        previous = signal.signal(signal.SIGTERM, lambda *args: stopped.set())
    runtime.start()
    try:
        count = 0
        while not stopped.is_set() and (ticks == 0 or count < ticks):
            emit({'mode': 'live', 'robot': runtime.state(), 'behaviors': runtime.behavior_state(),
                  'ai_required': False})
            count += 1
            if ticks == 0 or count < ticks:stopped.wait(interval)
    except KeyboardInterrupt:
        pass
    finally:
        runtime.close()
        if previous is not None:signal.signal(signal.SIGTERM, previous)
