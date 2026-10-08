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
            state[name] = {"observed_at": timestamp, "health": "ok", "observation": driver.observe()}
        except Exception as error:
            state[name] = {"observed_at": timestamp, "health": "error", "error": str(error)}
    return {"simulation": True, "devices": state,
            "body_pose": None, "head_pose": None}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Robot platform prototype (simulation only)")
    parser.add_argument("--config", type=Path, default=Path("robot.json"))
    sub = parser.add_subparsers(dest="verb", required=True)
    init = sub.add_parser("init", help="Create a robot configuration")
    init.add_argument("name")
    sub.add_parser("drivers", help="List installed driver plugins")
    add = sub.add_parser("add", help="Add a device; omit options for interactive selection")
    add.add_argument("kind", choices=["sensor", "motor"])
    add.add_argument("name", nargs="?")
    add.add_argument("--driver")
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
    try:
        drivers = registry()
        if args.verb == "drivers":
            emit({name: {"kind": cls.kind, "simulation": name.startswith("sim-")}
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
            kind = args.kind if args.verb == "add" else input("Device kind (sensor/motor): ").strip()
            if kind not in ("sensor", "motor"):
                raise ValueError("Device kind must be sensor or motor")
            choices = {n: c for n, c in drivers.items() if c.kind == kind}
            name = getattr(args, "name", None) or input("Device name: ").strip()
            selected = getattr(args, "driver", None)
            if not selected:
                print("Available drivers: " + ", ".join(choices))
                selected = input("Driver: ").strip()
            if not name or any(d["name"] == name for d in config["devices"]):
                raise ValueError("Device name must be nonempty and unique")
            if selected not in choices:
                raise ValueError("Unknown driver or driver kind mismatch; run robot drivers")
            config["devices"].append({"name": name, "kind": kind, "driver": selected})
            save(args.config, config)
            print(f"Added {name} using {selected}")
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
        # This starter deliberately refuses external hardware plugins at execution.
        # Discovery/configuration work now; hardware execution needs a future contract.
        devices = {}
        for device in config["devices"]:
            name = device["driver"]
            if name not in ("sim-camera", "sim-tfmini", "sim-motor"):
                raise ValueError("This release executes only built-in simulated drivers")
            devices[device["name"]] = drivers[name](device)
        if args.verb == "command":
            if args.name not in devices:
                raise ValueError("Device not found")
            emit(devices[args.name].command({"action": args.action, "value": args.value}))
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
                print("Stopped simulation.")
        return 0
    except (ValueError, OSError, KeyError, EOFError) as error:
        parser.exit(2, f"robot: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
