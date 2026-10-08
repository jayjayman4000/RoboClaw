"""Run from a cloned checkout: python install.py."""
import os
from pathlib import Path
import subprocess
import sys
import venv


def main():
    if sys.version_info < (3, 10):
        raise SystemExit("RoboClaw requires Python 3.10 or newer.")
    root = Path(__file__).resolve().parent
    environment = root / ".venv"
    print("\nRoboClaw | Terminal installation\n")
    print("Creating the project environment...")
    venv.EnvBuilder(with_pip=True).create(environment)
    scripts = environment / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    subprocess.run([str(python), "-m", "pip", "install", "-e", str(root)], check=True)
    # A user-level command shim delegates to the isolated installation.
    target = Path.home() / ".roboclaw" / "bin"
    target.mkdir(parents=True, exist_ok=True)
    for command in ("robot", "roboclaw"):
        if os.name == "nt":
            shim = target / (command + ".cmd")
            content = f'@echo off\n"{scripts / (command + ".exe")}" %*\n'
        else:
            import shlex
            shim = target / command
            content = '#!/bin/sh\nexec ' + shlex.quote(str(scripts / command)) + ' "$@"\n'
        if shim.exists() and "RoboClaw" not in shim.read_text() and str(scripts) not in shim.read_text():
            raise SystemExit(f"Refusing to overwrite existing command: {shim}")
        shim.write_text(content, encoding="utf-8")
        if os.name != "nt":
            shim.chmod(0o755)
    if str(target) not in os.environ.get("PATH", "").split(os.pathsep):
        if os.name == "nt":
            if input("Add RoboClaw commands to your user PATH? [Y/n]: ").strip().lower() not in ("n", "no"):
                import winreg
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                    try:
                        current, _ = winreg.QueryValueEx(key, "Path")
                    except FileNotFoundError:
                        current = ""
                    if str(target).casefold() not in [p.casefold() for p in current.split(";")]:
                        winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, current.rstrip(";") + ";" + str(target))
                print("User PATH updated. Restart your terminal application to use robot or roboclaw.")
        else:
            print(f'For future terminals, add this to your shell profile: export PATH="{target}:$PATH"')
    print("\nStarting guided setup...\n")
    return subprocess.call([str(python), "-m", "robot_platform.cli", "setup"], cwd=root)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Installation stopped: {error}")
