"""Generate a user systemd unit; do not install or start it implicitly."""
import platform
import sys
from pathlib import Path


def quote(value):
    value=str(value)
    if any(ord(c)<32 for c in value):raise ValueError('Service arguments cannot contain control characters')
    return '"'+value.replace('\\','\\\\').replace('"','\\"').replace('%','%%').replace('$','$$')+'"'


def unit(config_path,devices,python=None):
    if platform.system()!='Linux':raise ValueError('Generate the systemd service on the Raspberry Pi/Linux host after installing RoboClaw there')
    args=[python or sys.executable,'-m','robot_platform.cli','--config',str(Path(config_path).resolve()),'watch']
    for name in devices:args+=['--device',name]
    return '''[Unit]
Description=RoboClaw read-only hardware and AI health monitor
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
Environment=PYTHONUNBUFFERED=1
ExecStart='''+' '.join(quote(arg) for arg in args)+'''
Restart=on-failure
RestartSec=5
TimeoutStopSec=15

[Install]
WantedBy=default.target
'''
