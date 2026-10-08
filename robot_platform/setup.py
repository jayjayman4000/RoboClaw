"""Terminal onboarding. Planned hardware is explicitly disabled."""
from pathlib import Path


def choose(prompt, options):
    print("\n" + prompt)
    for index, label in enumerate(options, 1):
        print(f"  {index}. {label}")
    while True:
        value = input("Choose a number [1]: ").strip() or "1"
        if value.isdigit() and 1 <= int(value) <= len(options):
            return int(value) - 1
        print("Please enter one of the listed numbers.")


def yes(prompt):
    while True:
        value = input(prompt + " [Y/n]: ").strip().lower()
        if value in ("", "y", "yes"):
            return True
        if value in ("n", "no"):
            return False
        print("Enter yes or no.")


def onboard(path, read, save, snapshot, drivers):
    print("RoboClaw | Robot setup\n")
    print("This release supports simulation. Hardware and AI connections are planned.")
    if path.exists():
        current = read(path)
        if not yes(f"Update existing robot '{current['robot']}'? Original devices will be retained"):
            return
    else:
        current = {"schema_version": 1, "robot": "bb8", "devices": []}
    name = input(f"Robot name [{current['robot']}]: ").strip() or current["robot"]
    profile = choose("Robot profile", ["BB-8 spherical robot", "Custom robot"])
    mode = choose("Starting mode", ["Simulation: working virtual devices", "Plan hardware: drivers not connected yet"])
    desired = [
        ("camera", "sensor", "sim-camera", "Raspberry Pi Camera Module 3 Wide NoIR", "picamera2"),
        ("lidar", "sensor", "sim-tfmini", "TFmini Plus single-beam rangefinder", "tfmini-plus"),
        ("drive", "motor", "sim-motor", "Hub motor through VESC-compatible controller", "vesc"),
    ]
    devices = [dict(device) for device in current["devices"]]
    for device_name, kind, simulated, label, planned in desired:
        if any(d["name"] == device_name for d in devices):
            print(f"Keeping existing device: {device_name}")
            continue
        if yes(f"Add {label}?"):
            device = {"name": device_name, "kind": kind,
                      "driver": simulated if mode == 0 else planned, "enabled": mode == 0}
            if mode != 0:
                device["status"] = "planned; driver unavailable"
                device["connection"] = input("Planned connection (COM port, CSI, etc.; blank if unknown): ").strip() or None
            devices.append(device)
    data = {**current, "robot": name, "profile": "bb8" if profile == 0 else "custom",
            "mode": "simulation" if mode == 0 else "planning", "devices": devices,
            "ai_backend": {"status": "not connected"}}
    print("\nConfiguration review")
    print(f"Robot: {name} | Mode: {data['mode']} | AI: not connected")
    for device in devices:
        print(f"  {device['name']}: {device['driver']} ({'enabled' if device.get('enabled', True) else 'planned'})")
    if not yes("Save this configuration?"):
        print("Cancelled. Configuration unchanged.")
        return
    save(path, data)
    print(f"\nSaved {path}")
    active = {d["name"]: drivers[d["driver"]](d) for d in devices
              if d.get("enabled", True) and d["driver"] in ("sim-camera", "sim-tfmini", "sim-motor")}
    if active and yes("Run a simulated sensor check now?"):
        result = snapshot(active)
        for name, reading in result["devices"].items():
            print(f"  {name}: {reading['health']} (simulation)")
    print("\nSetup complete. Next commands: robot status, robot inspect, robot run")
    print("Run robot setup again to review configuration; robot configure to add a device.")
