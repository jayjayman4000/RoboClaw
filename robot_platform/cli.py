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
    demo = sub.add_parser("demo", help="Exercise the ESP32 parser offline; no saved configuration or hardware used")
    discovery = sub.add_parser("discover", help="Read controller identity from one selected port or offline demo")
    discovery.add_argument("--port")
    discovery.add_argument("--demo", action="store_true")
    discovery.add_argument("--timeout", type=float, default=5)
    discovery.add_argument("--save-as", help="Configure discovered capabilities and save a named bridge")
    demo.add_argument("--interval", type=float, default=0.5)
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
    test.add_argument("--require-fresh", action="store_true", help="Pass only on usable sensor telemetry")
    test.add_argument("--timeout", type=float, default=5)
    mood = sub.add_parser("mood", help="Send one BB8 v2.1 buzzer request and wait for head acknowledgment")
    mood.add_argument("name")
    from .bb8_bridge import MOODS
    mood.add_argument("mood", choices=MOODS)
    mood.add_argument("--timeout", type=float, default=5)
    hardware = sub.add_parser("hardware", help="Detect and enable firmware hardware extensions")
    hardware_sub = hardware.add_subparsers(dest="hardware_verb",required=True)
    hardware_setup = hardware_sub.add_parser("setup")
    hardware_setup.add_argument("name")
    hardware_setup.add_argument("--timeout",type=float,default=5)
    light = sub.add_parser("light",help="Read ambient light from a configured head sensor")
    light.add_argument("name")
    light.add_argument("--timeout",type=float,default=5)
    illumination = sub.add_parser("illumination",help="Switch configured head illumination explicitly")
    illumination.add_argument("name")
    illumination.add_argument("state",choices=["on","off"])
    illumination.add_argument("--timeout",type=float,default=5)
    behavior = sub.add_parser("behavior", help="Run a local darkness behavior; preview by default")
    behavior.add_argument("name")
    behavior.add_argument("--allow-illumination", action="store_true", help="Authorize automatic illumination writes for this session")
    behavior.add_argument("--dark", type=float, default=20)
    behavior.add_argument("--bright", type=float, default=35)
    behavior.add_argument("--hold", type=float, default=2)
    behavior.add_argument("--cooldown", type=float, default=10)
    behavior.add_argument("--ticks", type=int, default=0)
    behaviors = sub.add_parser("behaviors", help="Saved local behavior settings and permissions")
    behaviors_sub = behaviors.add_subparsers(dest="behaviors_verb", required=True)
    behaviors_sub.add_parser("list")
    behavior_setup = behaviors_sub.add_parser("setup")
    behavior_setup.add_argument("name")
    personality = sub.add_parser("personality", help="Configure sensor-triggered expressive reactions")
    personality_sub = personality.add_subparsers(dest="personality_verb", required=True)
    personality_sub.add_parser("list")
    personality_setup = personality_sub.add_parser("setup")
    personality_setup.add_argument("name")
    live = sub.add_parser("live", help="Run configured local behaviors without a chat prompt")
    live.add_argument("--device", action="append", default=[])
    live.add_argument("--ticks", type=int, default=0)
    live.add_argument("--interval", type=float, default=1)
    live.add_argument("--autonomous-ai", action="store_true")
    autonomy = sub.add_parser("autonomy", help="Configure bounded autonomous AI decisions")
    autonomy_sub = autonomy.add_subparsers(dest="autonomy_verb", required=True)
    autonomy_sub.add_parser("setup")
    autonomy_sub.add_parser("status")
    remove = sub.add_parser("remove")
    remove.add_argument("name")
    sub.add_parser("configure", help="Interactively add a device")
    sub.add_parser("status")
    caps = sub.add_parser("capabilities", help="Control AI action permissions")
    caps_sub = caps.add_subparsers(dest="cap_verb", required=True)
    caps_sub.add_parser("list")
    caps_sub.add_parser("setup")
    for verb in ("enable", "disable"):
        cap = caps_sub.add_parser(verb)
        cap.add_argument("action", choices=["read_robot_state", "set_buzzer_mood", "set_illumination"])
        cap.add_argument("--device")
    ai = sub.add_parser("ai", help="Configure local, remote or hosted AI")
    ai_sub = ai.add_subparsers(dest="ai_verb", required=True)
    ai_setup = ai_sub.add_parser("setup")
    ai_setup.add_argument("--network", choices=["tailscale", "direct"])
    ai_setup.add_argument("--mode", choices=["local", "remote", "api"])
    ai_setup.add_argument("--api-key-env")
    ai_setup.add_argument("--endpoint")
    ai_setup.add_argument("--model")
    ai_setup.add_argument("--timeout", type=float, default=None)
    ai_test = ai_sub.add_parser("test")
    ai_test.add_argument("--timeout", type=float, default=None)
    ai_sub.add_parser("status")
    ai_doctor = ai_sub.add_parser("doctor")
    ai_doctor.add_argument("--endpoint")
    ai_doctor.add_argument("--mode", choices=["local", "remote", "api"])
    chat_parser = sub.add_parser("chat", help="Chat with local AI using current sensor state and buzzer tools")
    chat_parser.add_argument("--device", action="append", default=[])
    chat_parser.add_argument("--debug", action="store_true")
    chat_parser.add_argument("--autonomous-ai", action="store_true")
    chat_parser.add_argument("--behaviors", action="store_true", help="Start configured local behaviors alongside chat")
    chat_parser.add_argument("--timeout", type=float, default=None)
    inspect = sub.add_parser("inspect", help="Read one state snapshot")
    inspect.add_argument("--device", action="append", default=[], help="Observe only named devices")
    run = sub.add_parser("run", help="Stream observations; Ctrl+C stops")
    run.add_argument("--device", action="append", default=[], help="Observe only named devices")
    run.add_argument("--ticks", type=int, default=0)
    run.add_argument("--interval", type=float, default=1.0)
    watch_parser = sub.add_parser("watch", help="Read-only hardware and AI health monitor; no interactive input")
    watch_parser.add_argument("--device", action="append", default=[])
    watch_parser.add_argument("--ticks", type=int, default=0)
    watch_parser.add_argument("--interval", type=float, default=1)
    watch_parser.add_argument("--ai-interval", type=float, default=15)
    watch_parser.add_argument("--state-file", type=Path)
    service_parser = sub.add_parser("service", help="Generate a Linux user systemd monitor service")
    service_parser.add_argument("--device", action="append", default=[])
    service_parser.add_argument("--mode", choices=["watch", "live"], default="watch")
    service_parser.add_argument("--autonomous-ai", action="store_true")
    service_parser.add_argument("--output", type=Path)
    command = sub.add_parser("command", help="Send one simulated motor command")
    command.add_argument("name")
    command.add_argument("action", choices=["stop", "set_speed"])
    command.add_argument("--value", type=float, default=0)
    args = parser.parse_args(argv)
    devices = {}
    try:
        if args.verb == "discover":
            from .discovery import discover
            from .demo import discovery_demo
            from .setup import apply_discovery, normalize_windows_port, check_connection_unique
            if bool(args.port) == bool(args.demo):
                raise ValueError("Choose exactly one of --port PORT or --demo")
            if not 0.1 <= args.timeout <= 60:
                raise ValueError("timeout must be between 0.1 and 60 seconds")
            if args.demo and args.save_as:
                raise ValueError("Demo identity cannot be saved as hardware")
            port = normalize_windows_port(args.port) if args.port and os.name == "nt" else args.port
            result = discovery_demo() if args.demo else discover({"port": port}, args.timeout)
            emit(result)
            if args.save_as and result["discovered"]:
                config = read(args.config)
                if not args.save_as.strip() or any(d["name"] == args.save_as for d in config["devices"]):
                    raise ValueError("Device name must be nonempty and unique")
                check_connection_unique(config["devices"], {"port": port})
                device = apply_discovery({"name": args.save_as, "kind": "sensor", "driver": "esp32-json",
                                          "enabled": True, "port": port, "baud": 115200}, result["controller"])
                from .setup import yes
                if yes("Save discovered device?"):
                    config["devices"].append(device)
                    save(args.config, config)
            return 0 if result["discovered"] else 1
        if args.verb == "demo":
            from .demo import run_demo
            if not .05 <= args.interval <= 60:
                raise ValueError("interval must be between 0.05 and 60 seconds")
            for state in run_demo():
                emit(state)
                time.sleep(args.interval)
            return 0
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
            emit({name: {"kind": cls.kind, "simulation": getattr(cls, "simulation", False), "fields": getattr(cls, "fields", {}), "capabilities": getattr(cls, "capabilities", {})}
                  for name, cls in drivers.items()})
            return 0
        if args.verb == "init":
            if args.config.exists():
                raise ValueError("Configuration already exists; choose another --config path")
            save(args.config, {"schema_version": 1, "robot": args.name, "devices": []})
            print(f"Created {args.config} for {args.name}")
            return 0
        config = read(args.config)
        if args.verb == "autonomy":
            from .autonomy import configure as configure_autonomy, settings as autonomy_settings
            if args.autonomy_verb == "setup":
                return 0 if configure_autonomy(args.config, config, save) else 1
            emit(autonomy_settings(config))
            return 0
        if args.verb == "personality":
            from .reactions import settings as reaction_settings, configure as configure_reactions, PROFILES
            if args.personality_verb == "setup":
                return 0 if configure_reactions(args.config, config, save, args.name) else 1
            emit({"devices": reaction_settings(config), "profiles": PROFILES})
            return 0
        if args.verb == "behaviors":
            from .behaviors import settings as behavior_settings, configure as configure_behaviors
            if args.behaviors_verb == "setup":
                return 0 if configure_behaviors(args.config, config, save, args.name) else 1
            emit({"devices": behavior_settings(config), "scope": "Local behaviors; separate from AI tool permissions"})
            return 0
        if args.verb == "capabilities":
            from .capabilities import report, configure, set_permission
            if args.cap_verb == "setup":
                return 0 if configure(args.config, config, save, drivers) else 1
            if args.cap_verb in ("enable", "disable"):
                config = set_permission(config, args.action, args.cap_verb == "enable", args.device)
                save(args.config, config)
                print("Saved. Restart chat to apply the new permissions.")
            emit(report(config, drivers))
            return 0
        if args.verb == "ai":
            from .ai_backend import configure_ai, backend_from_settings, doctor
            if args.ai_verb == "setup":
                return 0 if configure_ai(args.config, config, save, args.endpoint, args.model, args.timeout, args.mode, args.api_key_env, args.network) else 1
            settings = config.get("ai_backend", {})
            if args.ai_verb == "status":
                emit(settings)
                return 0
            if args.ai_verb == "doctor":
                report = doctor(settings, args.endpoint, args.mode)
                emit(report)
                return 0 if report["ok"] else 1
            backend = backend_from_settings(settings, args.timeout)
            checked = backend.check()
            print("Testing AI model response...", flush=True)
            response = backend.complete([{"role":"user","content":"Reply with Ready. No tools are available."}], [])
            if response.get("tool_calls") or not response.get("content", "").strip():
                raise ValueError("Model did not return a usable test response")
            emit({**checked, "inference_test": True, "response": response["content"]})
            return 0
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
            config.get("behaviors", {}).pop(args.name, None)
            config.get("reactions", {}).pop(args.name, None)
            save(args.config, config)
            return 0
        if args.verb == "status":
            emit(config)
            return 0
        if args.verb == "hardware":
            from .hardware import configure
            return 0 if configure(args.config,config,save,args.name,args.timeout) else 1
        if args.verb in ("light","illumination"):
            from .hardware import operate
            result=operate(config,args.name,args.verb,getattr(args,"state",None),args.timeout)
            emit(result)
            return 0 if result.get("usable",result.get("acknowledged",False)) else 1
        if args.verb == "behavior":
            from .hardware import device_for
            from .behaviors import Darkness, run as run_behavior
            from .bb8_bridge import BB8Bridge
            Darkness(args.dark, args.bright, args.hold, args.cooldown)
            if args.ticks < 0: raise ValueError("ticks must be >= 0")
            device = device_for(config, args.name)
            if not {"ambient_light", "illumination"}.issubset(device.get("extensions", [])):
                raise ValueError("Enable ambient_light and illumination with robot hardware setup first")
            devices[args.name] = BB8Bridge(device)
            run_behavior(devices[args.name], args.name, emit, args.dark, args.bright,
                         args.hold, args.cooldown, args.allow_illumination, ticks=args.ticks)
            return 0
        if args.verb == "mood":
            device = next((d for d in config["devices"] if d["name"] == args.name), None)
            if not device or device["driver"] != "bb8-v2" or not device.get("enabled", True):
                raise ValueError("mood requires an enabled bb8-v2 device; esp32-json stays read-only")
            from .setup import settings
            cls = drivers["bb8-v2"]
            options = {k: device[k] for k in cls.fields if k in device}
            driver = cls({**device, **settings(cls, options, interactive=False)})
            devices[args.name] = driver
            result = driver.command({"action": "mood", "mood": args.mood, "timeout": args.timeout})
            emit(result)
            return 0 if result["acknowledged"] else 1
        if args.verb == "test":
            from .serial_driver import connection_test
            device = next((d for d in config["devices"] if d["name"] == args.name), None)
            if not device or device["driver"] not in ("esp32-json", "bb8-v2") or not device.get("enabled", True):
                raise ValueError("test requires an enabled serial bridge device")
            if not 0.1 <= args.timeout <= 60: raise ValueError("timeout must be between 0.1 and 60 seconds")
            result = connection_test(device, args.timeout, require_fresh=args.require_fresh)
            emit(result)
            return 0 if result["passed"] else 1
        if args.verb == "service":
            from .service import unit
            enabled = {d['name'] for d in config['devices'] if d.get('enabled',True)}
            if set(args.device)-enabled:raise ValueError('Selected device does not exist or is disabled')
            if args.mode == "live":
                from .behaviors import settings as behavior_settings
                from .reactions import settings as reaction_settings
                behavior_settings(config);reaction_settings(config)
            if args.autonomous_ai:
                from .autonomy import settings as autonomy_settings
                if not autonomy_settings(config)['enabled']:raise ValueError('Enable autonomous AI with autonomy setup first')
            content = unit(args.config,args.device,mode=args.mode,autonomous_ai=args.autonomous_ai)
            if args.output:
                if args.output.resolve() == args.config.resolve():raise ValueError('Service output cannot overwrite robot configuration')
                args.output.parent.mkdir(parents=True,exist_ok=True)
                with args.output.open('x',encoding='utf-8') as stream:stream.write(content)
                print(f'Generated {args.output}; see README for systemctl startup instructions.')
            else:print(content,end='')
            return 0
        if args.verb == "watch" and args.state_file and args.state_file.resolve() == args.config.resolve():
            raise ValueError('State file cannot overwrite robot configuration')
        from .setup import settings
        selected = getattr(args, "device", [])
        if selected and set(selected) - {d["name"] for d in config["devices"] if d.get("enabled", True)}:
            raise ValueError("Selected device does not exist or is disabled")
        for device in config["devices"]:
            if selected and device["name"] not in selected: continue
            if not device.get("enabled", True): continue
            cls = drivers[device["driver"]]
            options = {k: device[k] for k in getattr(cls, "fields", {}) if k in device}
            if args.verb in ("chat", "watch", "live") and not selected and getattr(cls, "simulation", False): continue
            devices[device["name"]] = cls({**device, **settings(cls, options, interactive=False)})
        if args.verb == "live":
            from .live import run_live
            run_live(config, devices, snapshot, emit, args.interval, args.ticks, args.autonomous_ai)
        elif args.verb == "watch":
            from .monitor import watch
            watch(config,devices,snapshot,emit,args.interval,args.ai_interval,args.ticks,args.state_file,save)
        elif args.verb == "chat":
            from .agent import chat
            chat(config, devices, snapshot, args.debug, args.timeout, args.behaviors, args.autonomous_ai)
        elif args.verb == "command":
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
