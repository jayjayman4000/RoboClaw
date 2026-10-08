# RoboClaw

Terminal-first robot platform. Python 3.10+ and Git required.

## Install

```bash
git clone https://github.com/jayjayman4000/RoboClaw.git
cd RoboClaw
python install.py
```

Windows: `py install.py`. The installer creates an isolated environment, installs
RoboClaw and opens terminal setup. Accept the Windows PATH update and restart your
terminal. Linux/macOS: follow the printed PATH instructions. Keep the checkout in
place; installation links to its source. Update with `git pull`, then rerun the
installer. Existing configurations are retained.

Setup lists installed drivers, asks for a device name and driver-specific settings,
and saves only after review. Repeat to add more devices. Existing devices are kept.
`robot configure` adds one device. AI is not connected yet.

## Connect your existing ESP32 body firmware

Plug the **body** ESP32 into USB and close Arduino Serial Monitor or other programs
using that port. The head sends LiDAR measurements to the body over ESP-NOW.

```bash
robot ports
robot configure
```

Choose `esp32-json`, name it `head_range`, enter the body port (e.g. `COM3` on
Windows or `/dev/ttyACM0` on Linux), and accept 115200 baud and the 1-second stale
threshold. Or add it explicitly:

```bash
robot add sensor head_range --driver esp32-json --set port=COM3
robot test head_range --timeout 10
robot run --interval 0.1
```

Port discovery does not open every port or identify firmware from USB IDs. The
connection test opens only the selected port and succeeds on recognized telemetry,
not on the mere presence of an ESP32. Some boards reset when their serial port is
opened; use a longer test timeout if necessary. This adapter sends no commands.

Current BodyModule4 output works without reflashing. Distance is converted from cm
to meters. Signal strength, sensor validity and sample age are **unknown** with that
firmware. Its health is `unverified` even while USB telemetry arrives because the
head can retransmit old measurements. Do not use this state to authorize motion.
See [firmware review](docs/firmware-review.md) and [telemetry protocol](docs/telemetry.md).

## State and connection handling

`robot inspect` polls once; freshly opened hardware may report `waiting`.
`robot run` keeps drivers open, streams state, and closes them on Ctrl+C.
Disconnected serial devices retry every 2 seconds. A successful reconnect clears
previous readings. Historical values may appear while disconnected or stale, with
`usable: false`. No range readings are fabricated.

Health: `waiting` (open, no telemetry), `disconnected`, `unverified` (legacy
firmware), `invalid` (v1 reports failure), `stale`, or `ok`. `received_at` is UTC host
receipt time; `received_age_s` uses a monotonic clock. `observed_at` is polling time,
not capture time. Body/head pose and head orientation remain unknown. Malformed
lines and unrelated boot/WiFi messages are counted; partial lines are buffered.

```bash
robot setup
robot drivers
robot status
robot inspect
robot remove DEVICE
robot command drive set_speed --value 0.2
robot command drive stop
```

Motor commands currently work with the simulated motor only and last for one
process. The ESP32 driver is read-only. Simulation camera scenes are synthetic,
not captured images. No motor controller, camera capture, AI or sensor fusion is
implemented. Run `robot` with no arguments to open setup. Configuration defaults
to `~/.roboclaw/robot.json`; use `robot --config PATH ...` to select another file.
Previously configured disabled hardware placeholders remain disabled.

## Driver plugins

Install trusted plugin packages into RoboClaw's `.venv`, then restart the CLI.
Their drivers automatically appear in setup:

```toml
[project.entry-points."robot_platform.drivers"]
my-range = "my_package:MyRange"
```

A driver class accepts the device configuration, declares `kind` (`sensor` or
`motor`), `simulation` (defaults to false for external drivers), and optionally
`label` and `fields`. `observe()` returns a JSON-serializable dict with observations
and optionally `health`. `close()` releases resources; it is called on exit.
`command(action)` is optional. Configuration fields use `type` (`str`, `int`,
`float`), `required`, `default`, `min` and `max`; see `SerialTelemetry.fields`.
Drivers must keep observations bounded and handle their transport timeouts.
Plugin discovery imports installed code; it is not a sandbox. An adapter's own
commands determine hardware behavior. This release does not provide an actuator
safety contract or isolation for blocking third-party drivers.

## Verification

```bash
python -m unittest discover -s tests -v
```

## Windows troubleshooting

The installer cannot change the PATH of the PowerShell process that launched it.
To use commands immediately in that terminal:

```powershell
$env:Path = "$env:USERPROFILE\.roboclaw\bin;" + $env:Path
robot ports
```

Or, from the checkout, bypass PATH:

```powershell
.\.venv\Scripts\robot.exe ports
```

If discovery lists no ports, check that the boards are connected, the cable carries
USB data, and Windows Device Manager lists a serial port. Use that exact port
name. Numeric entries such as `5` are normalized to `COM5` on Windows, but do not
prove that COM5 exists. The adapter reads the body bridge, not the head's startup
messages. Correct an existing device using `robot remove NAME` then
`robot add sensor NAME --driver esp32-json --set port=COM5` with the actual port.

## Develop without connected hardware

Run `robot demo` (or `.\.venv\Scripts\robot.exe demo` in PowerShell) to exercise
the production ESP32 JSON parser using a virtual serial transport. No board,
serial port, or saved configuration is required. Your robot settings are untouched.

The demo shows partial messages, valid distance and signal strength, malformed
input, invalid measurements, stale sensor samples while USB remains active,
telemetry timeout, unplugging, reconnecting, and unverified legacy readings.
All output is labeled simulation. Scenario time advances deterministically;
`--interval 0.5` controls only the display pace, not the freshness thresholds.

This tests the host parser and health handling. It does not prove physical USB,
ESP-NOW, TFmini acquisition, or firmware compatibility. The v1 frames follow
`docs/telemetry.md`; existing firmware remains supported as unverified legacy.

## Discover controllers and select capabilities

```powershell
robot discover --demo
robot discover --port COM5
robot discover --port COM5 --save-as BodyV1
```

The offline discovery demo needs no hardware or saved configuration. Its future
LED ring is explicitly unsupported. Demo identity cannot be saved as hardware.
Real discovery listens on only your selected port for periodic hello messages;
it sends no commands and does not probe other ports. Default timeout is 5 seconds.
Legacy firmware without hello still works with manual configuration.

`--save-as` asks which supported capabilities to enable, then saves after review
to an existing robot configuration. Unknown drivers are displayed but cannot be
enabled through this adapter. The esp32-json setup offers discovery after entering
connection settings; skip while unplugged. One bridge entry owns one serial port.

Identity advertises support, not measured presence. Identity alone does not refresh
sensor readings. Saved discovered devices require the same controller ID at runtime;
a different controller reports identity_mismatch and cannot produce usable readings.
Unselected range capabilities report disabled and usable: false. The adapter remains
read-only. No AI, LED commands or physical motor control is added.

Matching telemetry-only head/body prototypes and limitations are in
[firmware/README.md](firmware/README.md). They have not been Arduino-compiled or flashed.
