"""Sensor-triggered expressive reactions, without object or navigation claims."""
from copy import deepcopy
import math

PROFILES = {
    'cat': {'change_m': .25, 'settle_s': .7, 'cooldown_s': 30},
    'bird': {'change_m': .25, 'settle_s': .7, 'cooldown_s': 30},
    'shy': {'change_m': .5, 'settle_s': 1.5, 'cooldown_s': 90},
}
DEFAULTS = {'enabled': False, 'allow_buzzer': False, 'profile': 'cat', **PROFILES['cat']}


class RangeChanges:
    """Detect settled beam changes. Cooldown events are discarded, not queued."""
    def __init__(self, change_m=.25, settle_s=.7, cooldown_s=30):
        for v in (change_m, settle_s, cooldown_s):
            if type(v) not in (int, float) or not math.isfinite(v):
                raise ValueError('Reaction settings must be finite numbers')
        if not .05 <= change_m <= 10 or not .3 <= settle_s <= 10 or not 10 <= cooldown_s <= 600:
            raise ValueError('Require change 0.05–10m, settle 0.3–10s, cooldown 10–600s')
        self.change, self.settle, self.cooldown = change_m, settle_s, cooldown_s
        self.baseline = None
        self.candidate = None
        self.since = None
        self.last_event = float('-inf')
        self.last_receipt = None

    def update(self, observation, now):
        value = observation.get('distance_m')
        fresh = (observation.get('usable') is True and observation.get('head_link_valid', True) is True
                 and type(value) in (int, float) and math.isfinite(value) and value > 0
                 and observation.get('received_at') is not None)
        if not fresh:
            self.baseline = self.candidate = self.since = self.last_receipt = None
            return {'status': 'unavailable', 'event': None}
        receipt = observation['received_at']
        if receipt == self.last_receipt:
            return {'status': 'waiting_for_new_sample', 'event': None}
        self.last_receipt = receipt
        if self.baseline is None:
            self.baseline = value
            return {'status': 'baseline', 'event': None}
        if abs(value - self.baseline) < self.change:
            self.candidate = self.since = None
            return {'status': 'steady', 'event': None}
        # Require the changed range to settle; don't react to a moving/noisy beam.
        if self.candidate is None or abs(value - self.candidate) > min(.05, self.change / 2):
            self.candidate, self.since = value, now
            return {'status': 'settling', 'event': None}
        if now - self.since < self.settle:
            return {'status': 'settling', 'event': None}
        before = self.baseline
        self.baseline = value
        self.candidate = self.since = None
        event = {'type': 'range_changed', 'previous_distance_m': before, 'distance_m': value,
                 'delta_m': round(value - before, 4), 'received_at': receipt,
                 'meaning': 'single-beam distance changed; object identity unknown'}
        allowed = now - self.last_event >= self.cooldown
        event['reaction_allowed'] = allowed
        if allowed:self.last_event = now
        return {'status': 'reaction' if allowed else 'cooldown', 'event': event}


def settings(config):
    rows = config.get('reactions', {})
    if not isinstance(rows, dict):raise ValueError('reactions must be keyed by device name')
    devices = {d['name']: d for d in config['devices']}
    result = {}
    for name, overrides in rows.items():
        if name not in devices or not isinstance(overrides, dict) or set(overrides) - set(DEFAULTS):
            raise ValueError('Unknown reaction device or setting')
        profile = overrides.get('profile', 'cat')
        if not isinstance(profile, str) or profile not in PROFILES:raise ValueError('Choose cat, bird or shy')
        row = {**DEFAULTS, **PROFILES[profile], **overrides}
        if type(row['enabled']) is not bool or type(row['allow_buzzer']) is not bool:
            raise ValueError('Reaction permissions must be boolean')
        RangeChanges(*(row[k] for k in ('change_m', 'settle_s', 'cooldown_s')))
        if row['enabled'] and not devices[name].get('enabled', True):
            raise ValueError('Reactions require an enabled device')
        result[name] = row
    return deepcopy(result)


def configure(path, config, save, name):
    from .drivers import registry
    from .setup import choose, yes
    device = next((d for d in config['devices'] if d['name'] == name and d.get('enabled', True)), None)
    if device is None:raise ValueError('Select an enabled observation device')
    cls = registry().get(device['driver'])
    if cls is None:raise ValueError('Device driver is not installed')
    supports_sound = bool(getattr(cls, 'capabilities', {}).get('mood'))
    settings(config)
    print('Personality chooses behavioral intentions from sensor events. Movement is not connected yet.')
    row = dict(DEFAULTS)
    row['enabled'] = yes('Enable reactions to sustained range sensor changes?')
    if row['enabled']:
        choices = list(PROFILES)
        profile = choices[choose('Personality: cat = investigate; bird = give space then re-engage; shy = cautious and infrequent', choices)]
        row.update(PROFILES[profile]);row['profile'] = profile
        row['allow_buzzer'] = yes('Allow spontaneous curious sounds?') if supports_sound else False
        if not supports_sound:print('This device has no mood output; intentions will still be reported.')
        for key, label in [('change_m', 'Minimum distance change (meters)'),
                           ('settle_s', 'Stable change required (seconds)'),
                           ('cooldown_s', 'Minimum time between reactions (seconds)')]:
            value = input(f'{label} [{row[key]}]: ').strip()
            if value:row[key] = float(value)
    updated = deepcopy(config)
    updated.setdefault('reactions', {})[name] = row
    settings(updated)
    if not yes('Save personality and reaction permissions?'):
        print('Cancelled. Settings unchanged.');return False
    save(path, updated)
    print('Saved. Use robot live or chat --behaviors.');return True


class Temperament:
    """Hardware-independent intentions. Never treats a beam as a person detector."""
    def __init__(self, profile):
        if profile not in PROFILES:raise ValueError('Unknown personality profile')
        self.profile = profile
        self.clear_distance = None

    def reset(self):
        self.clear_distance = None

    def decide(self, event):
        closer = event['delta_m'] < 0
        if self.profile == 'cat':
            intent = 'investigate_change' if closer else 'continue_exploring'
            sound = 'curious'
        else:
            sound = None
            if closer:
                if self.clear_distance is None:self.clear_distance = event['previous_distance_m']
                else:self.clear_distance = max(self.clear_distance, event['previous_distance_m'])
                intent = 'give_space'
            elif self.clear_distance is not None and event['distance_m'] >= self.clear_distance - .05:
                self.clear_distance = None
                intent = 'reengage'
                sound = 'curious' if self.profile == 'bird' else None
            else:
                intent = 'wait_at_distance' if self.clear_distance is not None else 'continue_exploring'
        return {'intent': intent, 'sound': sound,
                'evidence': event, 'certainty': 'range cue only; person or object identity unverified',
                'movement': {'executed': False, 'reason': 'No autonomous motion adapter is connected'}}
