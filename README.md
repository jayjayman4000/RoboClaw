# RoboClaw

Terminal-first robot platform prototype. Python 3.10+ and Git required.

## Install and start guided setup

```bash
git clone https://github.com/jayjayman4000/RoboClaw.git
cd RoboClaw
python install.py
```

On Windows, use `py install.py` if `python` is unavailable.
The installer creates an isolated environment, installs RoboClaw, and starts the
terminal wizard. Choose a robot profile, simulation or hardware planning, and
sensors/motors; review and save; then run a simulated check.
No API key is requested: the AI backend is not implemented yet.

On Windows, accept the user PATH update, then restart your terminal application.
On Linux/macOS the installer prints a PATH line to add to your shell profile.
Afterward `robot` and `roboclaw` are available:

```bash
robot setup
robot status
robot inspect
robot run --ticks 5
```

Running `robot` without arguments opens setup. Configuration defaults to
`~/.roboclaw/robot.json`, independent of your terminal's working directory.
Use `robot --config PATH setup` for another configuration. Existing devices are
retained; declining the final save leaves your configuration unchanged.

## Update an existing checkout

```bash
git pull
python install.py
```

Your old `robot.json` is not deleted or automatically imported. To update it
explicitly, run `robot --config robot.json setup` in its directory.
Keep the cloned folder in place: installation is linked to its source.

Hardware planning records disabled device placeholders. It does not connect real
motors/cameras or test them. Simulation checks exercise synthetic observations.

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
