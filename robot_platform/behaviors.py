"""Local observation-driven behaviors; no model calls or firmware changes."""
import math
import time


class Darkness:
    """One request per sustained zone, including failures; no reconnect replay."""
    def __init__(self, dark=20, bright=35, hold=2, cooldown=10):
        values = (dark, bright, hold, cooldown)
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
            raise ValueError('Behavior settings must be finite numbers')
        if not 0 <= dark < bright <= 100 or not .5 <= hold <= 60 or not 5 <= cooldown <= 300:
            raise ValueError('Require 0 <= dark < bright <= 100, hold 0.5–60s, cooldown 5–300s')
        self.dark, self.bright, self.hold, self.cooldown = values
        self.candidate = None
        self.since = None
        self.attempted = None
        self.last_request = float('-inf')

    def update(self, observation, now):
        level = observation.get('light_percent')
        fresh = (observation.get('light_usable') is True
                 and observation.get('illumination_state_usable') is True
                 and type(observation.get('illumination_on')) is bool
                 and type(level) in (int, float) and math.isfinite(level) and 0 <= level <= 100)
        zone = ('dark' if level <= self.dark else 'bright' if level >= self.bright else None) if fresh else None
        if zone is None:
            self.candidate, self.since = None, None
            return {'status': 'unavailable' if not fresh else 'between_thresholds', 'request': None}
        if zone != self.candidate:
            self.candidate, self.since = zone, now
        desired = zone == 'dark'
        if now - self.since < self.hold:
            return {'status': 'settling', 'zone': zone, 'request': None}
        # A sustained opposite zone allows the next transition even if no write was needed.
        if self.attempted != zone and observation['illumination_on'] == desired:
            self.attempted = zone
        if self.attempted == zone:
            return {'status': 'already_handled', 'zone': zone, 'request': None}
        if now - self.last_request < self.cooldown:
            return {'status': 'cooldown', 'zone': zone, 'request': None}
        self.attempted, self.last_request = zone, now
        return {'status': 'requested', 'zone': zone, 'request': desired}


def run(driver, name, emit, dark=20, bright=35, hold=2, cooldown=10,
        execute=False, interval=.1, ticks=0):
    if type(execute) is not bool or type(ticks) is not int or ticks < 0:
        raise ValueError('Invalid behavior execution options')
    if type(interval) not in (int, float) or not math.isfinite(interval) or not .05 <= interval <= .25:
        raise ValueError('Behavior polling interval must be 0.05–0.25 seconds')
    behavior = Darkness(dark, bright, hold, cooldown)
    tick = 0
    try:
        while ticks == 0 or tick < ticks:
            observation = driver.observe()
            decision = behavior.update(observation, time.monotonic())
            result = None
            if decision['request'] is not None and execute:
                try:
                    result = driver.command({'action': 'illumination', 'on': decision['request'], 'timeout': 5})
                except (OSError, ValueError) as error:
                    result = {'acknowledged': False, 'error': str(error)}
            emit({'behavior': 'darkness', 'device': name, 'mode': 'active' if execute else 'preview',
                  'thresholds': {'dark_percent': dark, 'bright_percent': bright, 'hold_s': hold, 'cooldown_s': cooldown},
                  'observation': observation, 'decision': decision, 'outcome': result})
            tick += 1
            if ticks == 0 or tick < ticks:
                time.sleep(interval)
    except KeyboardInterrupt:
        pass
