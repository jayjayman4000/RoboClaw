"""Controller manifest validation and passive discovery on one selected connection."""
import time


def validate_manifest(data):
    if data.get('protocol_version') != 1 or type(data.get('protocol_version')) is not int:
        raise ValueError('Unsupported identity protocol')
    result = {'protocol_version': 1}
    for field in ('controller_id', 'name', 'firmware_version'):
        value = data.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > 128:
            raise ValueError('Invalid identity ' + field)
        result[field] = value
    capabilities = data.get('capabilities')
    if not isinstance(capabilities, list) or len(capabilities) > 32:
        raise ValueError('Invalid capabilities')
    result['capabilities'] = []
    ids = set()
    for capability in capabilities:
        if not isinstance(capability, dict):
            raise ValueError('Invalid capability')
        cid, kind = capability.get('id'), capability.get('kind')
        if not isinstance(cid, str) or not cid or len(cid) > 64 or cid in ids:
            raise ValueError('Invalid or duplicate capability ID')
        if kind not in ('sensor', 'output'):
            raise ValueError('Invalid capability kind')
        ids.add(cid)
        item = {'id': cid, 'kind': kind}
        for key in ('driver', 'units'):
            value = capability.get(key)
            if not isinstance(value, str) or not value or len(value) > 64:
                raise ValueError('Invalid capability ' + key)
            item[key] = value
        # This bridge implements range observations only; advertisements are not executable code.
        item['host_supported'] = kind == 'sensor' and item['driver'] == 'tfmini-plus' and item['units'] == 'm'
        item['commands_enabled'] = False
        result['capabilities'].append(item)
    if sum(c['host_supported'] for c in result['capabilities']) > 1:
        raise ValueError('This bridge supports one TFmini channel')
    return result


def discover(config, timeout=5, driver_factory=None):
    from .serial_driver import SerialTelemetry
    driver = (driver_factory or SerialTelemetry)(config)
    deadline = time.monotonic() + timeout
    observation = None
    try:
        while time.monotonic() < deadline:
            observation = driver.observe()
            if observation.get('controller') is not None:
                return {'discovered': True, 'controller': observation['controller'],
                        'connection': observation['connection'], 'source': observation['source']}
            time.sleep(.05)
        return {'discovered': False, 'controller': None, 'observation': observation,
                'note': 'No identity received. Legacy telemetry may still work; firmware must broadcast hello.'}
    finally:
        driver.close()
