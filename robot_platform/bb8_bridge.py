"""Opt-in BB8 v2.1 buzzer output; the generic JSON bridge stays read-only."""
import json
import time
from .serial_driver import SerialTelemetry

MOODS = ('silent', 'happy', 'curious', 'talk', 'alarm', 'boot')

class BB8Bridge(SerialTelemetry):
    label = 'BB8 v2.1 bridge (range telemetry and acknowledged buzzer moods)'
    capabilities = {'mood': {'values': list(MOODS), 'acknowledged': True}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.events = []
        self.sleep = time.sleep

    def _accept(self, line):
        try:
            event = json.loads(line)
            if isinstance(event, dict) and event.get('type') in ('command_sent', 'command_ack', 'error'):
                kind = event['type']
                if kind != 'error' and (type(event.get('id')) is not int or not 0 <= event['id'] <= 0xffffffff):
                    raise ValueError('Invalid command ID')
                if kind == 'command_sent' and type(event.get('accepted_by_radio')) is not bool:
                    raise ValueError('Invalid radio acceptance')
                if kind == 'command_ack' and (type(event.get('mood')) is not int or not 0 <= event['mood'] < len(MOODS)):
                    raise ValueError('Invalid acknowledged mood')
                self.events.append(event)
                self.events = self.events[-32:]
                return
        except (ValueError, TypeError, UnicodeDecodeError):
            self.malformed += 1
            return
        super()._accept(line)

    def command(self, action):
        mood = action.get('mood')
        if action.get('action') != 'mood' or mood not in MOODS:
            raise ValueError('Supported action: mood with ' + ', '.join(MOODS))
        timeout = action.get('timeout', 5)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not .1 <= timeout <= 60:
            raise ValueError('timeout must be between 0.1 and 60 seconds')
        deadline = self.clock() + timeout
        result = {'action': 'mood', 'mood': mood, 'source': 'hardware', 'sent': False,
                  'accepted_by_radio': False, 'acknowledged': False, 'command_id': None,
                  'note': 'Acknowledgment reports head processing; it does not verify audible playback'}
        state = None
        while self.clock() < deadline:
            state = self.observe()
            if state.get('telemetry_schema') == 'bb8-v2' and state.get('head_link_valid') is True and state.get('received_age_s', 10) <= .35:
                break
            self.sleep(.05)
        else:
            return {**result, 'status': 'not_sent', 'error': 'No recent connected BB8 v2.1 head telemetry', 'observation': state}
        # Drop pre-command acknowledgments. Only one request is written, never auto-retried.
        self.events.clear()
        payload = (mood + '\n').encode('ascii')
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
                    if event['type'] == 'command_ack' and event['id'] == result['command_id'] and event['mood'] == MOODS.index(mood):
                        return {**result, 'acknowledged': True, 'status': 'acknowledged'}
            if state.get('connection') == 'disconnected':
                return {**result, 'status': 'disconnected', 'error': state.get('error')}
            self.sleep(.05)
        return {**result, 'status': 'ack_timeout', 'error': 'No matching head acknowledgment; command outcome unknown'}
