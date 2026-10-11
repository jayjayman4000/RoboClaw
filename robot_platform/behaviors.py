"""Local observation-driven behaviors; no model calls or firmware changes."""
import json
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
                    result = driver.command({'action': 'illumination', 'on': decision['request'], 'timeout': 1})
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


DEFAULTS = {'enabled': False, 'allow_illumination': False, 'dark': 20,
            'bright': 35, 'hold': 2, 'cooldown': 10}


def settings(config):
    """Validate saved autonomous permissions without opening hardware."""
    from copy import deepcopy
    rows = config.get('behaviors', {})
    if not isinstance(rows, dict):
        raise ValueError('behaviors must be an object keyed by device name')
    devices = {d['name']: d for d in config['devices']}
    result = {}
    for name, overrides in rows.items():
        if name not in devices or not isinstance(overrides, dict) or set(overrides) - set(DEFAULTS):
            raise ValueError('Unknown behavior device or setting')
        row = {**DEFAULTS, **overrides}
        if type(row['enabled']) is not bool or type(row['allow_illumination']) is not bool:
            raise ValueError('Behavior permissions must be boolean')
        Darkness(row['dark'], row['bright'], row['hold'], row['cooldown'])
        if row['enabled']:
            device = devices[name]
            if device['driver'] != 'bb8-v2' or not device.get('enabled', True) or not {'ambient_light', 'illumination'}.issubset(device.get('extensions', [])):
                raise ValueError('Enabled darkness behavior requires an enabled BB8 bridge with light and illumination')
        result[name] = row
    return deepcopy(result)


def configure(path, config, save, name):
    from copy import deepcopy
    from .hardware import device_for
    from .setup import yes
    device = device_for(config, name)
    if not {'ambient_light', 'illumination'}.issubset(device.get('extensions', [])):
        raise ValueError('Enable ambient light and illumination with hardware setup first')
    current = settings(config).get(name, DEFAULTS)
    row = dict(current)
    print('Local darkness behavior. Permissions are separate from AI actions. Chat requires --behaviors.')
    row['enabled'] = yes('Enable darkness decisions for this device?')
    if row['enabled']:
        row['allow_illumination'] = yes('Allow automatic illumination changes? No means preview only')
        for key, label in [('dark', 'Turn on at or below relative brightness (%)'),
                           ('bright', 'Turn off at or above relative brightness (%)'),
                           ('hold', 'Required sustained reading (seconds)'),
                           ('cooldown', 'Minimum time between requests (seconds)')]:
            answer = input(f'{label} [{current[key]}]: ').strip()
            row[key] = float(answer) if answer else current[key]
    else:
        row['allow_illumination'] = False
    updated = deepcopy(config)
    updated.setdefault('behaviors', {})[name] = row
    settings(updated)
    if not yes('Save behavior settings?'):
        print('Cancelled. Settings unchanged.')
        return False
    save(path, updated)
    print('Saved. Start chat with --behaviors to use these settings.')
    return True


class BehaviorEngine:
    """Called under the runtime lock; shares existing drivers with chat."""
    def __init__(self, rows, devices, trace=print, clock=time.monotonic, reactions=None):
        from collections import deque
        self.rows = {n: dict(r) for n, r in rows.items() if r['enabled'] and n in devices}
        self.devices, self.trace, self.clock = devices, trace, clock
        self.rules = {n: self.make_rule(r) for n, r in self.rows.items()}
        from .reactions import RangeChanges, Temperament
        self.reactions = {n: dict(r) for n, r in (reactions or {}).items() if r['enabled'] and n in devices}
        self.range_rules = {n: RangeChanges(*(r[k] for k in ('change_m', 'settle_s', 'cooldown_s'))) for n, r in self.reactions.items()}
        self.temperaments = {n: Temperament(r["profile"]) for n, r in self.reactions.items()}
        self.reaction_latest = {}
        self.paused = set()
        self.latest = {}
        self.events = deque(maxlen=20)

    @staticmethod
    def make_rule(row):
        return Darkness(*(row[k] for k in ('dark', 'bright', 'hold', 'cooldown')))

    def pause(self, name=None):
        names = [name] if name is not None else set(self.rows) | set(self.reactions)
        self.paused.update(n for n in names if n in self.rows or n in self.reactions)

    def resume(self):
        # Explicit user restart evaluates current evidence; no queued commands.
        for name in self.paused:
            if name in self.rows:self.rules[name] = self.make_rule(self.rows[name])
            if name in self.reactions:
                from .reactions import RangeChanges
                row = self.reactions[name]
                self.range_rules[name] = RangeChanges(*(row[k] for k in ('change_m', 'settle_s', 'cooldown_s')))
                self.temperaments[name].reset()
        self.paused.clear()

    def state(self):
        from copy import deepcopy
        return deepcopy({'settings': self.rows, 'paused_devices': sorted(self.paused),
                         'latest': self.latest, 'reactions': self.reactions, 'reaction_latest': self.reaction_latest, 'recent_events': list(self.events)})

    def step(self, snapshot):
        output_dispatched = False
        for name, rule in self.rules.items():
            if name in self.paused:
                self.latest[name] = {'status': 'paused', 'request': None}
                continue
            observation = snapshot.get('devices', {}).get(name, {}).get('observation', {})
            decision = rule.update(observation, self.clock())
            self.latest[name] = decision
            if decision['request'] is None:
                continue
            result = None
            if self.rows[name]['allow_illumination']:
                output_dispatched = True
                try:
                    result = self.devices[name].command({'action': 'illumination', 'on': decision['request'], 'timeout': 1})
                except Exception as error:
                    result = {'acknowledged': False, 'error': str(error)}
            event = {'device': name, 'behavior': 'darkness',
                     'mode': 'active' if self.rows[name]['allow_illumination'] else 'preview',
                     'decision': decision, 'outcome': result}
            self.events.append(event)
            self.trace('[behavior] ' + json.dumps(event))

        if output_dispatched:
            for name in self.range_rules:
                self.reaction_latest[name] = {'status': 'deferred_for_illumination', 'event': None}
            return
        for name, rule in self.range_rules.items():
            if name in self.paused:
                self.reaction_latest[name] = {'status': 'paused', 'event': None}
                continue
            observation = snapshot.get('devices', {}).get(name, {}).get('observation', {})
            decision = rule.update(observation, self.clock())
            self.reaction_latest[name] = decision
            if decision['status'] == 'unavailable':self.temperaments[name].reset()
            if decision['event'] is None:continue
            plan = self.temperaments[name].decide(decision['event'])
            self.reaction_latest[name]['plan'] = plan
            result = None
            supported = bool(getattr(self.devices[name], 'capabilities', {}).get('mood'))
            permitted = (self.reactions[name]['allow_buzzer'] and supported
                         and decision['event']['reaction_allowed'] and plan['sound'] is not None)
            if permitted:
                try:
                    result = self.devices[name].command({'action': 'mood', 'mood': plan['sound'], 'timeout': 1})
                except Exception as error:
                    result = {'acknowledged': False, 'error': str(error)}
            event = {'device': name, 'behavior': 'curiosity', 'profile': self.reactions[name]['profile'],
                     'mode': 'active' if permitted else 'intent_only', 'decision': decision, 'plan': plan, 'outcome': result}
            self.events.append(event)
            self.trace('[behavior] ' + json.dumps(event))
            if permitted:return  # Read a new snapshot before any other expressive output.
