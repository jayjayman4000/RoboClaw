# Robot platform starter

Version 0.1.0: a terminal workflow for configuring a robot and collecting shared
state from simulated devices. No hardware, paid API, ROS installation, or AI model
is needed. Python 3.10 or newer is required.

## Windows quick start

Extract this archive and open PowerShell in the extracted `robot-platform` folder.

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\robot.exe init bb8
.\.venv\Scripts\robot.exe add sensor camera --driver sim-camera
.\.venv\Scripts\robot.exe add sensor lidar --driver sim-tfmini
.\.venv\Scripts\robot.exe add motor drive --driver sim-motor
.\.venv\Scripts\robot.exe status
.\.venv\Scripts\robot.exe inspect
.\.venv\Scripts\robot.exe run --ticks 5
```

Using the full executable path avoids PowerShell activation-policy changes.
If `py` is unavailable, install Python from https://www.python.org/downloads/.

## macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
robot init bb8
robot add sensor camera --driver sim-camera
robot add sensor lidar --driver sim-tfmini
robot add motor drive --driver sim-motor
robot run --ticks 5
```

## Commands

`robot configure` interactively asks for device kind, name, and driver.
`robot drivers` lists registered plugins. `robot remove NAME` removes a configured
device. `robot --config PATH ...` selects another robot configuration; the global
option goes before the subcommand. Existing configurations are not overwritten.

```bash
robot command drive set_speed --value 0.2
robot command drive stop
robot inspect
```

Commands are one-shot demonstrations. They do not control a running `robot run`
process and do not persist motor speed. Speed is normalized, not meters/second.

## What you should see

State output includes UTC observation timestamps, per-device health, a synthetic
camera scene, and a varying single-beam distance. Camera `frame` is null: this is
not image capture or visual inference. Body and head pose remain unknown. A range
reading is not assigned to a person or chair in the synthetic camera scene.

## Scope

This is the CLI and device-contract prototype, not a finished autonomy platform.
It has no AI backend, actual camera frames, TFmini serial parser, ESP32 firmware,
motor-controller connection, synchronized sensor fusion, or network service.
The hardware list remains Pi 4, ESP32-S3s, TFmini Plus, and ordered Camera Module 3
Wide NoIR. Head angle feedback is not assumed available.

Next: implement a recorded-image/camera adapter, TFmini transport and parser,
freshness rules and record/replay, then a read-only model adapter. Select RAI/OM1
integration after exercising these contracts; this prototype does not replace ROS
or make a claim to hardware-independent autonomy.

## Plugin contract

Built-in drivers live in `robot_platform/drivers.py`. A driver takes a device
configuration, declares `kind`, and supplies `observe()` and optionally
`command(action)`. An installable extension can advertise its class using:

```toml
[project.entry-points."robot_platform.drivers"]
my-driver = "my_package:MyDriver"
```

External plugins can be discovered and added to configuration, but this release
only executes the three built-in simulation drivers. Hardware plugins need a
proper lifecycle, timeout, units, calibration, and command/result contract first.
Install only plugins you trust: entry-point discovery imports their code.

## Verification

```bash
python -m unittest discover -s tests -v
```
