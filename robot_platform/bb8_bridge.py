"""Opt-in BB8 v2.1 buzzer output; the generic JSON bridge stays read-only."""
import json
import time
from .serial_driver import SerialTelemetry

MOODS = ('silent', 'happy', 'curious', 'talk', 'alarm', 'boot')
SOUNDS = ('hello', 'yes', 'no', 'question', 'acknowledge', 'excited', 'confused', 'warning', 'goodbye')

class BB8Bridge(SerialTelemetry):
    label = 'BB8 v2.1 bridge (range telemetry and acknowledged buzzer moods)'
    capabilities = {'mood': {'values': list(MOODS), 'acknowledged': True}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.capabilities = dict(type(self).capabilities)
        extensions=self.config.get('extensions',[])
        if not isinstance(extensions,list) or set(extensions)-{'ambient_light','illumination','droid_language'}:raise ValueError('Unknown BB8 extensions')
        if 'illumination' in extensions:self.capabilities['illumination']={'values':[False,True],'acknowledged':True}
        if 'droid_language' in extensions:self.capabilities['sound']={'values':list(SOUNDS),'acknowledged':True}
        self.events = []
        self.sleep = time.sleep

    def _accept(self, line):
        try:
            event = json.loads(line)
            if isinstance(event, dict) and event.get('type') in ('command_sent', 'command_ack', 'illumination_ack', 'sound_ack', 'error'):
                kind = event['type']
                if kind != 'error' and (type(event.get('id')) is not int or not 0 <= event['id'] <= 0xffffffff):
                    raise ValueError('Invalid command ID')
                if kind == 'command_sent' and type(event.get('accepted_by_radio')) is not bool:
                    raise ValueError('Invalid radio acceptance')
                if kind == 'command_ack' and (type(event.get('mood')) is not int or not 0 <= event['mood'] < len(MOODS)):
                    raise ValueError('Invalid acknowledged mood')
                if kind == 'illumination_ack' and type(event.get('on')) is not bool:raise ValueError('Invalid illumination acknowledgment')
                if kind == 'sound_ack' and (type(event.get('sound')) is not int or not 0 <= event['sound'] < len(SOUNDS)):
                    raise ValueError('Invalid acknowledged sound')
                self.events.append(event)
                self.events = self.events[-32:]
                return
        except (ValueError, TypeError, UnicodeDecodeError):
            self.malformed += 1
            return
        super()._accept(line)

    def observe(self):
        state=super().observe()
        if 'ambient_light' not in self.config.get('extensions',[]):
            for key in ('light_raw','light_age_ms','light_percent','light_units'):state.pop(key,None)
            state['light_usable']=False
        if 'illumination' not in self.config.get('extensions',[]):
            state.pop('illumination_on',None);state['illumination_state_usable']=False
        return state

    def command(self, action):
        mood = action.get('mood')
        sound = action.get('sound')
        is_light = action.get('action') == 'illumination'
        is_sound = action.get('action') == 'sound'
        if is_light:
            if 'illumination' not in self.capabilities or type(action.get('on')) is not bool:
                raise ValueError('Enable illumination hardware and supply on as a boolean')
        elif is_sound:
            if 'sound' not in self.capabilities or sound not in SOUNDS:
                raise ValueError('Enable droid_language and choose: ' + ', '.join(SOUNDS))
        elif action.get('action') != 'mood' or mood not in MOODS:
            raise ValueError('Supported action: mood with ' + ', '.join(MOODS))
        timeout = action.get('timeout', 5)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not .1 <= timeout <= 60:
            raise ValueError('timeout must be between 0.1 and 60 seconds')
        deadline = self.clock() + timeout
        result = {'action': 'mood', 'mood': mood, 'source': 'hardware', 'sent': False,
                  'accepted_by_radio': False, 'acknowledged': False, 'command_id': None,
                  'note': 'Acknowledgment reports head processing; it does not verify audible playback'}
        if is_light:
            result.update(action='illumination', on=action['on'], note='Acknowledgment confirms head GPIO processing; it does not verify emitted light')
            result.pop('mood')
        elif is_sound:
            result.update(action='sound', sound=sound)
            result.pop('mood')
        state = None
        while self.clock() < deadline:
            state = self.observe()
            compatible = (not is_light or state.get('illumination_supported') is True) and (not is_sound or state.get('sound_supported') is True)
            if state.get('telemetry_schema') == 'bb8-v2' and state.get('head_link_valid') is True and state.get('received_age_s', 10) <= .35 and compatible:
                break
            self.sleep(.05)
        else:
            return {**result, 'status': 'not_sent', 'error': 'No recent compatible BB8 head telemetry', 'observation': state}
        # Drop pre-command acknowledgments. Only one request is written, never auto-retried.
        self.events.clear()
        if is_light:
            line = 'illumination ' + ('on' if action['on'] else 'off')
        elif is_sound:
            line = 'sound ' + sound
        else:
            line = mood
        payload = (line + '\n').encode('ascii')
        try:
            self.serial.write_timeout = .5
            if self.serial.write(payload) != len(payload):
                return {**result, 'status': 'write_failed', 'error': 'Incomplete serial write; command outcome unknown'}
            result['sent'] = True
        except Exception as error:
            return {**result, 'status': 'write_failed', 'error': str(error)}
        while self.clock() < deadline:
            state = self.observe()
            for event in self.events:
                if event['type'] == 'error':
                    return {**result, 'status': 'rejected', 'error': event.get('error', 'firmware error')}
                if event['type'] == 'command_sent' and result['command_id'] is None:
                    result['command_id'] = event['id']
                    result['accepted_by_radio'] = event['accepted_by_radio']
                    if not result['accepted_by_radio']:
                        return {**result, 'status': 'radio_rejected'}
            if result['command_id'] is not None:
                for event in self.events:
                    matches = (
                        is_light and event['type'] == 'illumination_ack' and event['on'] == action['on']
                        or is_sound and event['type'] == 'sound_ack' and event['sound'] == SOUNDS.index(sound)
                        or not is_light and not is_sound and event['type'] == 'command_ack' and event['mood'] == MOODS.index(mood)
                    )
                    if event['id'] == result['command_id'] and matches:
                        return {**result, 'acknowledged': True, 'status': 'acknowledged'}
            if state.get('connection') == 'disconnected':
                return {**result, 'status': 'disconnected', 'error': state.get('error')}
            self.sleep(.05)
        return {**result, 'status': 'ack_timeout', 'error': 'No matching head acknowledgment; command outcome unknown'}
