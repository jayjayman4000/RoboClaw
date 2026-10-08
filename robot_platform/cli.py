import argparse
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from .drivers import registry


def emit(value):
    print(json.dumps(value, indent=2))


def read(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("devices"), list):
        raise ValueError("Unsupported robot configuration")
    return data


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def snapshot(devices):
    state = {}
    for name, driver in devices.items():
        timestamp = datetime.now(timezone.utc).isoformat()
        try:
            observation = driver.observe()
            state[name] = {"observed_at": timestamp, "health": observation.get("health", "ok"), "observation": observation}
        except Exception as error:
            state[name] = {"observed_at": timestamp, "health": "error", "error": str(error)}
    return {"simulation": all(getattr(d, "simulation", False) for d in devices.values()), "devices": state,
            "body_pose": None, "head_pose": None}


def main(argv=None):
    parser = argparse.ArgumentParser(description="RoboClaw robot platform")
    parser.add_argument("--config", type=Path, default=Path.home() / ".roboclaw" / "robot.json")
    sub = parser.add_subparsers(dest="verb", required=False)
    init = sub.add_parser("init", help="Create a robot configuration")
    init.add_argument("name")
    sub.add_parser("setup", help="Guided first-run setup")
    sub.add_parser("drivers", help="List installed driver plugins")
    add = sub.add_parser("add", help="Add a device; omit options for interactive selection")
    add.add_argument("kind", choices=["sensor", "motor"])
    add.add_argument("name", nargs="?")
    add.add_argument("--driver")
    add.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    sub.add_parser("ports", help="List serial ports without opening them")
    test = sub.add_parser("test", help="Test selected ESP32 telemetry connection")
    test.add_argument("name")
    test.add_argument("--timeout", type=float, default=5)
    remove = sub.add_parser("remove")
    remove.add_argument("name")
    sub.add_parser("configure", help="Interactively add a device")
    sub.add_parser("status")
    sub.add_parser("inspect", help="Read one state snapshot")
    run = sub.add_parser("run", help="Stream observations; Ctrl+C stops")
    run.add_argument("--ticks", type=int, default=0)
    run.add_argument("--interval", type=float, default=1.0)
    command = sub.add_parser("command", help="Send one simulated motor command")
    command.add_argument("name")
    command.add_argument("action", choices=["stop", "set_speed"])
    command.add_argument("--value", type=float, default=0)
    args = parser.parse_args(argv)
    devices = {}
    try:
        drivers = registry()
        if args.verb == "ports":
            from .serial_driver import ports
            emit(ports())
            return 0
        if args.verb in (None, "setup"):
            from .setup import onboard
            onboard(args.config, read, save, snapshot, drivers)
            return 0
        if args.verb == "drivers":
            emit({name: {"kind": cls.kind, "simulation": getattr(cls, "simulation", False), "fields": getattr(cls, "fields", {})}
                  for name, cls in drivers.items()})
            return 0
        if args.verb == "init":
            if args.config.exists():
                raise ValueError("Configuration already exists; choose another --config path")
            save(args.config, {"schema_version": 1, "robot": args.name, "devices": []})
            print(f"Created {args.config} for {args.name}")
            return 0
        config = read(args.config)
        if args.verb in ("add", "configure"):
            from .setup import select_device
            supplied = None
            if args.verb == "add" and args.driver:
                supplied = {}
                for option in args.set:
                    key, sep, value = option.partition("=")
                    if not sep: raise ValueError("Settings must be KEY=VALUE")
                    supplied[key] = value
            device = select_device(drivers, config["devices"],
                                   getattr(args, "kind", None), getattr(args, "name", None),
                                   getattr(args, "driver", None), supplied)
            config["devices"].append(device)
            save(args.config, config)
            print(f"Added {device['name']} using {device['driver']}")
            return 0
        if args.verb == "remove":
            if not any(d["name"] == args.name for d in config["devices"]):
                raise ValueError("Device not found")
            config["devices"] = [d for d in config["devices"] if d["name"] != args.name]
            save(args.config, config)
            return 0
        if args.verb == "status":
            emit(config)
            return 0
        if args.verb == "test":
            from .serial_driver import connection_test
            device = next((d for d in config["devices"] if d["name"] == args.name), None)
            if not device or device["driver"] != "esp32-json" or not device.get("enabled", True):
                raise ValueError("test requires an enabled esp32-json device")
            if not 0.1 <= args.timeout <= 60: raise ValueError("timeout must be between 0.1 and 60 seconds")
            result = connection_test(device, args.timeout)
            emit(result)
            return 0 if result["passed"] else 1
        from .setup import settings
        for device in config["devices"]:
            if not device.get("enabled", True): continue
            cls = drivers[device["driver"]]
            options = {k: device[k] for k in getattr(cls, "fields", {}) if k in device}
            devices[device["name"]] = cls({**device, **settings(cls, options, interactive=False)})
        if args.verb == "command":
            if args.name not in devices:
                raise ValueError("Device not found")
            emit(devices[args.name].command({"action": args.action, "value": args.value}))
            if getattr(devices[args.name], "simulation", False):
                print("One-shot simulation; command state ends when this process exits.")
        elif args.verb == "inspect":
            emit(snapshot(devices))
        elif args.verb == "run":
            if args.ticks < 0 or not .05 <= args.interval <= 60:
                raise ValueError("ticks must be >= 0; interval must be between 0.05 and 60 seconds")
            tick = 0
            try:
                while args.ticks == 0 or tick < args.ticks:
                    emit(snapshot(devices))
                    tick += 1
                    if args.ticks == 0 or tick < args.ticks:
                        time.sleep(args.interval)
            except KeyboardInterrupt:
                print("Stopped observations.")
        return 0
    except (ValueError, OSError, KeyError, EOFError, ImportError) as error:
        parser.exit(2, f"robot: {error}\n")
    finally:
        for driver in devices.values():
            close = getattr(driver, "close", None)
            if close: close()


if __name__ == "__main__":
    raise SystemExit(main())
