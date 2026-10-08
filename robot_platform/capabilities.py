"""Registry and persisted permissions for AI actions, separate from hardware setup."""
from copy import deepcopy

ACTIONS = {
    'read_robot_state': {'description':'Read live sensor observations and connection health','driver_capability':None},
    'set_illumination': {'description':'Turn configured illumination on or off','driver_capability':'illumination'},
    'set_buzzer_mood': {'description':'Request a supported buzzer mood','driver_capability':'mood'},
}


def policy(config):
    value = config.get('ai_capabilities', {})
    if not isinstance(value,dict) or set(value)-{'actions','devices'}:raise ValueError('Invalid AI capability policy')
    actions = value.get('actions',{})
    devices = value.get('devices',{})
    def validate(overrides):
        if not isinstance(overrides,dict) or set(overrides)-set(ACTIONS) or any(type(v) is not bool for v in overrides.values()):
            raise ValueError('AI capability overrides must use known action names and boolean values')
    validate(actions)
    if not isinstance(devices,dict):raise ValueError('Invalid AI device policy')
    for name,overrides in devices.items():
        if not isinstance(name,str):raise ValueError('Invalid AI device name')
        validate(overrides)
    return deepcopy(value)


def allowed(settings, action, device=None):
    if action not in ACTIONS:return False
    if not settings.get('actions',{}).get(action,True):return False
    return device is None or settings.get('devices',{}).get(device,{}).get(action,True)


def supported(driver, action):
    requirement = ACTIONS[action]['driver_capability']
    return requirement is None or bool(getattr(driver,'capabilities',{}).get(requirement))


def permitted_devices(devices, settings, action):
    return [name for name,driver in devices.items() if supported(driver,action) and allowed(settings,action,name)]


def report(config, drivers):
    settings = policy(config)
    rows=[]
    for action,spec in ACTIONS.items():
        devices=[]
        for item in config['devices']:
            cls = drivers.get(item['driver'])
            available = bool(item.get('enabled',True) and cls and (supported(cls,action) or (action=='set_illumination' and item['driver']=='bb8-v2' and 'illumination' in item.get('extensions',[]))))
            devices.append({'device':item['name'],'available':available,'enabled':allowed(settings,action,item['name']),
                            'effective':available and allowed(settings,action,item['name'])})
        rows.append({'action':action,'description':spec['description'],'enabled':allowed(settings,action),'devices':devices})
    return {'actions':rows,'scope':'AI tools only; manual commands and local sensor polling remain available'}


def set_permission(config, action, enabled, device=None):
    if action not in ACTIONS:raise ValueError('Unknown AI action')
    if type(enabled) is not bool:raise ValueError('Permission must be boolean')
    if device is not None and not any(d['name']==device for d in config['devices']):raise ValueError('Device not found')
    value = policy(config)
    if device is None:value.setdefault('actions',{})[action]=enabled
    else:value.setdefault('devices',{}).setdefault(device,{})[action]=enabled
    return {**config,'ai_capabilities':value}


def configure(path, config, save, drivers):
    from .setup import yes
    settings = report(config,drivers)
    updated = config
    print('AI action permissions. Global disable overrides all per-device permissions.')
    for row in settings['actions']:
        enabled = yes(f"Allow AI action {row['action']}? {row['description']}")
        updated = set_permission(updated,row['action'],enabled)
        if enabled:
            for item in row['devices']:
                if item['available']:
                    updated = set_permission(updated,row['action'],yes(f"Allow {row['action']} for {item['device']}?"),item['device'])
    if not yes('Save AI action permissions?'):
        print('Cancelled. Permissions unchanged.');return False
    save(path,updated)
    print('Saved. Restart chat to apply the new permissions.');return True
