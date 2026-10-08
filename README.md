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
`robot configure` adds one device. Configure local AI with `robot ai setup`.

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
not captured images. No motor controller, camera capture or sensor fusion is implemented.
Optional local AI chat uses Ollama. Run `robot` with no arguments to open setup. Configuration defaults
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

## Connect BB8 firmware v2.1 (HeadModule5 / BodyModule5)

Keep your currently flashed v2.1 firmware. The sketches in firmware/ are earlier
prototypes, not required upgrades. BodyModule5 emits sensor_valid, head_connected,
sample_age_ms, seq and rx_overwrites alongside dist and brake. This adapter
recognizes the complete shape as bb8-v2 without inventing a protocol version.
It accepts invalid null measurements, distinguishes head radio loss from USB loss,
and retains signal strength and diagnostics. Packet seq is not a sensor sample ID.
Reported sample age plus host elapsed time must be <=350 ms and within your
configured stale threshold for a reading to remain usable. Weak/overexposed
strength cannot be usable. rx_overwrites counts the body's overwritten pending
packets; it is not an end-to-end packet-loss measurement.

Close Arduino Serial Monitor. Connect only the body to your PC for RoboClaw,
keeping the head powered for ESP-NOW. List ports and inspect saved configuration:

```powershell
.\.venv\Scripts\robot.exe ports
.\.venv\Scripts\robot.exe status
.\.venv\Scripts\robot.exe test BodyModule --timeout 10 --require-fresh
.\.venv\Scripts\robot.exe run --device BodyModule --interval 0.1
```

Replace BodyModule with your configured bridge name. If it is not configured,
add it using esp32-json and the actual port. If an existing entry owns that port,
remove that entry before re-adding it with the correct settings. Do not configure
the head debug port as another telemetry bridge.

```powershell
.\.venv\Scripts\robot.exe add sensor BodyModule --driver esp32-json --set port=COM5
```

Replace COM5 with the actual body port. V2.1 does not emit our hello manifest, so
use manual configuration and skip identity discovery. Do not bind it to a saved
prototype identity/capability selection. A normal test checks recognized telemetry;
--require-fresh waits for usable sensor telemetry and fails if only invalid, stale
or disconnected data arrive. Neither test proves navigation readiness.

Expected: moving an object changes distance_m; disconnecting the LiDAR produces
invalid/usable:false; powering down the head produces head_disconnected/usable:false;
unplugging body USB produces disconnected, then automatic recovery on reconnect.
Ctrl+C ends streaming. No motor or buzzer commands are sent by this adapter.

## BB8 buzzer output with firmware v2.1

The new bb8-v2 plugin adds only the existing firmware's buzzer mood commands. The
generic esp32-json plugin stays read-only. Stop streaming with Ctrl+C and close
Arduino Serial Monitor before using another command on the same serial port.

```powershell
git fetch origin
git switch feature/bb8-mood-control
.\.venv\Scripts\robot.exe remove BodyModule
.\.venv\Scripts\robot.exe add sensor BodyModule --driver bb8-v2 --set port=COM4
.\.venv\Scripts\robot.exe mood BodyModule happy --timeout 10
.\.venv\Scripts\robot.exe mood BodyModule curious
.\.venv\Scripts\robot.exe mood BodyModule silent
.\.venv\Scripts\robot.exe run --device BodyModule --interval 0.1
```

Replace the name/port if needed. This driver uses the same telemetry settings and
does not require reflashing. Supported moods: silent, happy, curious, talk, alarm,
boot. Valid LiDAR distance is not required for audio, but recent recognized v2.1
telemetry must report the head connected. No hardware motor command is supported.

Output distinguishes not_sent, write_failed, radio_rejected, rejected, disconnected,
ack_timeout, and acknowledged. Only acknowledged returns success (exit code zero).
Radio acceptance means queued, not confirmed at the head. An acknowledgment must
match the returned command ID and requested mood. Prior/unrelated acknowledgments
cannot confirm the request. Timeout means outcome unknown; commands are not retried
automatically. Head acknowledgment confirms firmware processing, not audible output
or completion of the sound. This firmware does not authenticate ACK sender MACs;
acknowledgments are firmware-reported, not cryptographic delivery verification.

Each CLI command exclusively opens its selected bridge and closes it on exit.
Stop robot run before robot mood; simultaneous CLI access is unsupported. Local AI chat is available with robot ai setup. Driver capability metadata now exposes the mood action for
future agent integration; this does not authorize or implement other outputs.

## Local AI terminal chat (Ollama)

Install [Ollama for Windows](https://ollama.com/download/windows), keep it running,
and download a model with tool support. For a first test:

```powershell
ollama pull qwen3:4b
git fetch origin
git switch feature/local-ai-chat
.\.venv\Scripts\robot.exe ai setup
.\.venv\Scripts\robot.exe ai test
.\.venv\Scripts\robot.exe chat --device BodyModule --debug
```

Setup checks the local server, lists downloaded models, verifies tool support,
then saves after review. Default endpoint: http://localhost:11434. No API key,
new Python dependency, automatic download, Ollama installation or cloud backend
is used. Download/model memory requirements vary; if your computer struggles,
choose a smaller tool-capable model such as qwen3:1.7b.

Stop robot run and Arduino Serial Monitor before chat. Keep the head powered.
The existing bb8-v2 BodyModule on COM4 supports read_robot_state and set_buzzer_mood.
Read-only adapters expose observations only. Chat opens selected devices; with no
--device arguments it selects enabled hardware drivers and excludes simulated ones.
Explicitly selected simulations remain labeled simulation. No shell, file, motor,
LED or camera tools are provided to the model. Installed plugins remain trusted code.

Try: 'What distance is the LiDAR measuring?', 'Make a happy sound', 'Is the head
connected?' and 'Make a curious sound'. These are real local-model prompts, not
keyword scripts. Model answers depend on model quality; tool traces show the
observations and command outcomes used. No genuine model inference was performed
during development; API and agent tests use scripted server/model responses.

/state shows full live JSON; /tools lists available tools; /debug toggles tool
traces; /reset clears conversation history; /quit or Ctrl+C closes chat and devices.
Buzzer outcomes always print even without debug. At most one buzzer request is
executed per user turn. Unknown tools/invalid arguments are rejected, tool rounds
are bounded, and only complete recent conversation turns are retained in memory.

A background poller reads telemetry every 50 ms while the model runs. Driver I/O
is serialized with tool execution. Sensor health is recomputed when requested;
a previously valid range cannot be reused as usable after timeout/disconnection.
Responses are not synchronized capture-time perception or a guarantee of physical
safety. The head ACK reports firmware processing, not independent playback proof.

HTTP calls have a 60-second timeout. If local inference exceeds it, chat reports
an error without automatically retrying an action. First model loading can be slow.
Chat transcripts are not saved; robot configuration stores only backend settings.

References: [Ollama chat API](https://docs.ollama.com/api/chat),
[tool calling](https://docs.ollama.com/capabilities/tool-calling).
