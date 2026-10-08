"""Passive feature detection followed by user-selected host and AI permissions."""
import time
from copy import deepcopy
from .bb8_bridge import BB8Bridge
from .capabilities import set_permission


def device_for(config,name):
    device=next((d for d in config['devices'] if d['name']==name),None)
    if not device or device['driver']!='bb8-v2' or not device.get('enabled',True):raise ValueError('Select an enabled bb8-v2 bridge')
    return device


def recent(driver,timeout,predicate):
    if isinstance(timeout,bool) or not isinstance(timeout,(int,float)) or not .1<=timeout<=60:raise ValueError('timeout must be between 0.1 and 60 seconds')
    deadline=time.monotonic()+timeout
    state=None
    while time.monotonic()<deadline:
        state=driver.observe()
        if predicate(state):return state
        time.sleep(.05)
    return state


def configure(path,config,save,name,timeout=5,driver_factory=BB8Bridge):
    from .setup import yes
    device=device_for(config,name)
    driver=driver_factory({**device,'extensions':['ambient_light','illumination']})
    try:
        state=recent(driver,timeout,lambda s:s.get('head_link_valid') is True and s.get('received_age_s') is not None and s['received_age_s']<=.35 and ('light_supported' in s))
    finally:driver.close()
    if not state or not state.get('head_link_valid') or state.get('received_age_s') is None or state['received_age_s']>.35 or not (state.get('light_supported') or state.get('illumination_supported')):
        raise ValueError('No recent head light extensions detected. Flash both BB8-v2.2 sketches, close other serial sessions and retry.')
    updated=deepcopy(config);selected=[]
    print(f'Head hardware detected through {name}. Light GPIO1; illumination GPIO5. Firmware fixes these pins; host setup does not rewire them.')
    if state.get('light_supported') and yes('Enable ambient light readings? (relative brightness, not lux)'):selected.append('ambient_light')
    if state.get('illumination_supported') and yes('Enable illumination output?'):selected.append('illumination')
    device_for(updated,name)['extensions']=selected
    if 'illumination' in selected:
        updated=set_permission(updated,'set_illumination',yes('Allow AI to switch illumination when you request it?'),name)
    else:updated=set_permission(updated,'set_illumination',False,name)
    print('Enabled extensions: '+(', '.join(selected) or 'none'))
    if not yes('Save hardware configuration?'):
        print('Cancelled. Configuration unchanged.');return False
    save(path,updated)
    print(f'Saved. Test with robot light {name} and robot illumination {name} on/off. Restart chat to apply.')
    return True


def operate(config,name,verb,state=None,timeout=5,driver_factory=BB8Bridge):
    device=device_for(config,name)
    extension='ambient_light' if verb=='light' else 'illumination'
    if extension not in device.get('extensions',[]):raise ValueError(f'Enable {extension} first with robot hardware setup {name}')
    driver=driver_factory(device)
    try:
        if verb=='illumination':
            if state not in ('on','off'):raise ValueError('Choose on or off')
            return driver.command({'action':'illumination','on':state=='on','timeout':timeout})
        value=recent(driver,timeout,lambda s:s.get('light_usable') is True)
        value=value or {}
        return {'source':'hardware','light_raw':value.get('light_raw'),'light_percent':value.get('light_percent'),
                'units':'relative ADC percentage, not lux','usable':value.get('light_usable',False),
                'received_at':value.get('received_at'),'light_age_ms':value.get('light_age_ms'),
                'error':None if value.get('light_usable') else 'No fresh light reading before timeout'}
    finally:driver.close()
