"""Host-only Tailscale onboarding; never exposed as an AI tool."""
import json
import os
import platform
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path


def find_tailscale():
    found = shutil.which('tailscale')
    if found:return found
    if platform.system() == 'Windows':
        for base in [os.environ.get('ProgramW6432'), os.environ.get('ProgramFiles'), r'C:\Program Files']:
            if base:
                candidate = Path(base) / 'Tailscale' / 'tailscale.exe'
                if candidate.is_file():return str(candidate)
    return None


def run(command, **kwargs):
    try:
        return subprocess.run(command, check=True, timeout=kwargs.pop("timeout",300), **kwargs)
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError('Tailscale command failed. Check administrator access, service state and internet connectivity, then retry setup. ' + str(error)) from error


def install_tailscale():
    system = platform.system()
    print('Tailscale is missing. Installing it on this computer; administrator approval may be required.', flush=True)
    if system == 'Windows' and shutil.which('winget'):
        run([shutil.which('winget'),'install','--id','Tailscale.Tailscale','--exact','--source','winget','--accept-source-agreements','--accept-package-agreements'])
    elif system in ('Windows','Linux'):
        url = 'https://pkgs.tailscale.com/stable/tailscale-setup-latest.exe' if system == 'Windows' else 'https://tailscale.com/install.sh'
        with tempfile.TemporaryDirectory(prefix='roboclaw-tailscale-') as directory:
            target = Path(directory) / ('tailscale-setup.exe' if system == 'Windows' else 'install.sh')
            with urllib.request.urlopen(url,timeout=30) as response:
                data = response.read(100_000_001)
            if len(data)>100_000_000:raise ValueError('Tailscale installer exceeds download limit')
            target.write_bytes(data)
            if system == 'Windows':
                os.startfile(str(target))
                input('Complete the Tailscale installer, then press Enter to continue: ')
            else:
                prefix = [] if os.geteuid() == 0 else ['sudo']
                if prefix and not shutil.which('sudo'):raise ValueError('Administrator access required. Install Tailscale using https://tailscale.com/download, then retry.')
                run(prefix + ['sh',str(target)])
    else:
        raise ValueError('Automatic installation supports Windows and Linux/Raspberry Pi OS. Install Tailscale from https://tailscale.com/download, then retry.')


def status(executable):
    result = run([executable,'status','--json'],capture_output=True,text=True,timeout=10)
    try:
        data = json.loads(result.stdout)
        if not isinstance(data,dict):raise ValueError()
    except ValueError as error:raise ValueError('Invalid Tailscale status response') from error
    return data.get('BackendState')


def ensure_tailscale():
    executable = find_tailscale()
    if not executable:
        install_tailscale()
        executable = find_tailscale()
        if not executable:raise ValueError('Installation finished but the Tailscale CLI was not found. Restart your terminal and retry setup.')
    else:print('Tailscale is already installed; skipping installation.')
    state = status(executable)
    if state != 'Running':
        print(f'Tailscale state: {state}. Sign in or connect before entering the remote address.')
        if platform.system() == 'Windows':
            input('Open the Tailscale tray app, log in/connect, then press Enter: ')
        else:
            print('Starting tailscale up; follow its authentication link. Existing network preferences are retained.',flush=True)
            prefix = [] if os.geteuid() == 0 else ['sudo']
            run(prefix + [executable,'up'])
        if status(executable) != 'Running':raise ValueError('Tailscale is not connected. Complete sign-in and retry setup.')
    print('Tailscale is connected on this computer.')
    print('The remote Ollama computer must also have Tailscale installed and connected to an accessible tailnet. If missing, install it there: https://tailscale.com/download')
