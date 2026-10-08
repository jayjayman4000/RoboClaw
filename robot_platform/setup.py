"""Terminal setup populated by installed driver metadata."""
import math
import os


def choose(prompt, options):
    print('\n' + prompt)
    for i, label in enumerate(options, 1):
        print(f'  {i}. {label}')
    while True:
        value = input('Choose a number [1]: ').strip() or '1'
        if value.isdigit() and 1 <= int(value) <= len(options):
            return int(value) - 1
        print('Please enter one of the listed numbers.')


def yes(prompt):
    while True:
        value = input(prompt + ' [Y/n]: ').strip().lower()
        if value in ('', 'y', 'yes'): return True
        if value in ('n', 'no'): return False
        print('Enter yes or no.')


def normalize_windows_port(value):
    value = str(value).strip()
    if value.isdigit():
        value = 'COM' + value
    if value.upper().startswith('COM'):
        suffix = value[3:]
        if not suffix.isdigit() or int(suffix) < 1:
            raise ValueError('Enter a serial port such as COM4')
        value = 'COM' + str(int(suffix))
    return value


def settings(cls, supplied=None, interactive=True):
    result = dict(supplied or {})
    fields = getattr(cls, 'fields', {})
    if set(result) - set(fields):
        raise ValueError('Unknown driver settings: ' + ', '.join(set(result) - set(fields)))
    for key, spec in fields.items():
        value = result.get(key, spec.get('default'))
        if interactive:
            value = input(f'{key}' + (f' [{value}]' if value is not None else '') + ': ').strip() or value
        if value is None:
            if spec.get('required'): raise ValueError(f'{key} is required')
            continue
        converter = {'str': str, 'int': int, 'float': float}.get(spec.get('type', 'str'))
        if converter is None: raise ValueError(f'Unsupported field type for {key}')
        value = converter(value)
        if key == 'port' and os.name == 'nt':
            value = normalize_windows_port(value)
        if isinstance(value, (int, float)) and (not math.isfinite(value) or value < spec.get('min', -math.inf) or value > spec.get('max', math.inf)):
            raise ValueError(f'{key} outside allowed range')
        if spec.get('required') and not str(value).strip(): raise ValueError(f'{key} is required')
        result[key] = value
    return result


def select_device(drivers, devices, kind=None, name=None, selected=None, supplied=None):
    choices = {n: c for n, c in drivers.items() if kind is None or c.kind == kind}
    if not choices: raise ValueError('No installed drivers for this device kind')
    if selected is None:
        names = list(choices)
        selected = names[choose('Installed drivers', [f'{n}: {getattr(c, "label", c.__name__)}' for n, c in choices.items()])]
    if selected not in choices: raise ValueError('Unknown driver or driver kind mismatch')
    cls = choices[selected]
    name = name or input('Device name: ').strip()
    if not name or any(d['name'] == name for d in devices): raise ValueError('Device name must be nonempty and unique')
    if 'port' in getattr(cls, 'fields', {}) and supplied is None:
        from .serial_driver import ports
        print('Available serial ports (select by entering port below):')
        discovered = ports()
        for p in discovered: print(f'  {p["port"]}: {p["description"]}')
        if not discovered:
            print('  No ports detected. Check USB connection/cable and Device Manager. You can enter a port manually.')
        print('Enter the full port name, e.g. COM4 on Windows or /dev/ttyACM0 on Linux.')
    options = settings(cls, supplied, interactive=supplied is None)
    check_connection_unique(devices, options)
    device = {'name': name, 'kind': cls.kind, 'driver': selected, 'enabled': True, **options}
    if selected == 'esp32-json' and supplied is None and yes('Discover controller identity now? Skip when unplugged'):
        from .discovery import discover
        result = discover(device)
        if result['discovered']:
            apply_discovery(device, result['controller'])
        else:
            print(result['note'])
    return device


def onboard(path, read, save, snapshot, drivers):
    print('RoboClaw | Robot setup\nInstalled drivers support simulation and ESP32 bridges. Choose local, remote or hosted AI with robot ai setup.')
    current = read(path) if path.exists() else {'schema_version': 1, 'robot': 'bb8', 'devices': []}
    if path.exists() and not yes(f'Update existing robot {current["robot"]}? Existing devices will be retained'): return
    name = input(f'Robot name [{current["robot"]}]: ').strip() or current['robot']
    devices = [dict(d) for d in current['devices']]
    while yes('Add a device?'):
        devices.append(select_device(drivers, devices))
    data = {**current, 'robot': name, 'devices': devices}
    print('\nConfiguration review')
    for device in devices: print(f'  {device["name"]}: {device["driver"]}')
    if not yes('Save this configuration?'):
        print('Cancelled. Configuration unchanged.')
        return
    save(path, data)
    print(f'Saved {path}\nNext commands: robot ports, robot test DEVICE, robot inspect, robot run')
    if yes('Configure AI now?'):
        from .ai_backend import configure_ai
        configure_ai(path, data, save)
    if yes("Configure AI action permissions now?"):
        from .capabilities import configure
        configure(path, read(path), save, drivers)


def apply_discovery(device, controller):
    print(f"Controller: {controller['name']} | firmware {controller['firmware_version']}")
    enabled = []
    for capability in controller['capabilities']:
        label = f"{capability['id']}: {capability['driver']} ({capability['units']})"
        if capability['host_supported']:
            if yes('Enable ' + label + '?'):
                enabled.append(capability['id'])
        else:
            print('  ' + label + ' — advertised, host support unavailable')
    device['controller'] = controller
    device['enabled_capabilities'] = enabled
    return device


def check_connection_unique(devices, device):
    port = device.get('port')
    if not port:
        return
    for existing in devices:
        old_port = existing.get('port')
        if not existing.get('enabled', True) or not old_port:
            continue
        same = normalize_windows_port(old_port).casefold() == normalize_windows_port(port).casefold() if os.name == 'nt' else old_port == port
        if same:
            raise ValueError(f"Port {port} already belongs to {existing['name']}; remove that bridge before adding another")
