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

Inference calls default to a 180-second timeout, configurable with --timeout (10–600 seconds). If local inference exceeds it, chat reports
an error without automatically retrying an action. First model loading can be slow.
Chat transcripts are not saved; robot configuration stores only backend settings.

References: [Ollama chat API](https://docs.ollama.com/api/chat),
[tool calling](https://docs.ollama.com/capabilities/tool-calling).

### Slow local inference

Setup metadata calls succeeding while chat times out means the local server may
be reachable but generation/loading is too slow for the deadline. Version 0.5.1
distinguishes connection refusal from timeout, requests shorter replies with a
4096-token context, and adds Qwen3's /no_think soft hint alongside think:false.
This hint does not guarantee the model stops reasoning. Leaked think-tag preambles
are removed from displayed final content.

```powershell
git pull --ff-only
.\.venv\Scripts\robot.exe ai test --timeout 300
.\.venv\Scripts\robot.exe chat --device BodyModule --debug --timeout 300
```

No setup repeat is needed to use the new default. To persist a different limit:
`robot ai setup --timeout 300`. If generation is still too slow, inspect Ollama's
loaded models with `ollama ps` and its version with `ollama --version`; model
size, CPU/GPU use, available memory and template/version behavior need checking.
No hardware command runs until an actual valid tool request is received.

### Choose local, remote or hosted AI

`robot setup` offers AI configuration after saving devices. Run `robot ai setup` anytime and choose local Ollama, remote Ollama (Tailscale/LAN), or a hosted OpenAI-compatible Chat Completions API. Hardware stays on the computer running RoboClaw. Existing local configurations remain supported. Setup checks Ollama model tool support; hosted setup makes one small inference request to probe tools without executing hardware actions (provider charges may apply).

Remote example, from the laptop or robot computer:

```powershell
robot ai doctor --mode remote --endpoint http://100.111.212.1:11434
robot ai setup --mode remote --endpoint http://100.111.212.1:11434
robot ai test --timeout 300
robot chat --device BodyModule --debug --timeout 300
```

`ai doctor` reports DNS, TCP and API checks without inference, serial access or configuration changes. It works before AI setup has succeeded. `ai test` checks actual inference; chat never automatically replays a hardware action after a connection failure. Setup saves the selected endpoint and mode, independently of device configuration.

Both computers must be on your tailnet. On the gaming PC, inspect the listener and local service first:

```powershell
Get-NetTCPConnection -LocalPort 11434 -State Listen
Invoke-RestMethod http://localhost:11434/api/version
```

On the laptop:

```powershell
tailscale ping 100.111.212.1
Test-NetConnection 100.111.212.1 -Port 11434
```

A successful Tailscale ping does not prove port 11434 is accessible. Ollama listening only on loopback cannot accept direct Tailscale connections. After reviewing existing security rules, set the gaming PC's user environment variable `OLLAMA_HOST` to its Tailscale address (`100.111.212.1:11434`) and fully restart Ollama if direct access is desired. Check the listener again. Permit TCP 11434 only from the robot/laptop's Tailscale address in Windows Firewall and restrict access through your tailnet policy; do not disable the firewall or expose this port publicly. HTTP on this connection relies on Tailscale's encrypted transport; RoboClaw itself does not establish or authenticate a tailnet connection. HTTPS endpoints are also supported. See [Ollama networking configuration](https://github.com/ollama/ollama/blob/main/docs/faq.mdx) and [Tailscale access controls](https://tailscale.com/docs/features/access-control).

Hosted API example:

```powershell
$env:OPENAI_API_KEY = 'YOUR_KEY'
robot ai setup --mode api --endpoint https://api.openai.com/v1 --model YOUR_TOOL_CAPABLE_MODEL --api-key-env OPENAI_API_KEY
robot ai test
```

Keys are read from an environment variable and never written to robot.json, debug output or GitHub. Set the variable in each runtime terminal, or configure it in your service environment. Other providers must implement the OpenAI-compatible `/models` and `/chat/completions` endpoints with function tool calls; provider-specific APIs are not supported by this adapter. HTTPS is required for hosted APIs. Requests do not follow redirects or use system proxies. Conversation text and requested sensor/tool results are sent to the selected backend. Keep hosted API keys out of pasted logs.

AI action permissions are available through `robot capabilities`; see the capability management section below.

### Tailscale onboarding

Remote AI setup now asks whether to use Tailscale or a direct network. Tailscale setup detects an existing CLI (including the standard Windows install folder), skips installation when present, installs when missing, and verifies connection before asking for the remote endpoint. Windows uses WinGet, or the official installer if WinGet is unavailable. Linux including Raspberry Pi OS uses the official Tailscale installation script with sudo when needed. OS administrator prompts and Tailscale sign-in are handled interactively; failures stop setup without saving an AI endpoint. Installed software remains installed if you later cancel AI configuration. Other operating systems receive manual installation instructions. Existing security rules and tailnet preferences are not reset.

```powershell
robot ai setup --mode remote --network tailscale
# Already managed network / LAN: bypass Tailscale installation
robot ai setup --mode remote --network direct --endpoint http://100.111.212.1:11434
```

Onboarding reminds users to install/connect Tailscale on the remote model computer too. Local and hosted API setup never installs Tailscale. Existing saved remote configurations continue working without rerunning setup.

### Planned robot personality

Future animation setup will offer styles such as catlike curiosity, birdlike curiosity and shy behavior, plus expressiveness and animation frequency controls. This is a planned feature; no autonomous animation or motor behavior is enabled by these changes.

### AI capability management

Configure AI permissions after device setup, or run `robot capabilities setup` at any time. The initial actions are `read_robot_state` and `set_buzzer_mood`. Both default to enabled for compatible configured devices, preserving existing installations. Permissions can be global or per device; a global disable always overrides a device enable. Enabling an action never adds hardware support to a driver that lacks it.

```powershell
robot capabilities list
robot capabilities setup
robot capabilities disable set_buzzer_mood --device BodyModule
robot capabilities enable set_buzzer_mood --device BodyModule
robot capabilities disable read_robot_state
robot capabilities enable read_robot_state
```

Restart chat after changing saved permissions. `/tools` shows effective AI tools and `/capabilities` shows the session's policy. Disabled tools are excluded from the model request and rejected again at dispatch, even if the model invents a call. Sensor permissions filter observations by device; when only some devices are allowed, aggregate pose fields are withheld. These permissions govern AI tools: manual `robot mood`, `/state`, `robot inspect` and local telemetry polling stay available. Previous chat history is not reused between chat sessions; permissions do not remove data already sent to a provider.

Policy is stored in `ai_capabilities.actions` and `ai_capabilities.devices` in robot.json. Capability changes preserve AI connection settings and hardware configuration. A central action registry in `robot_platform/capabilities.py` defines action descriptions, driver requirements and policy resolution for both the CLI and AI dispatcher. Future hardware actions must add a registry entry, tool schema and validated handler.

### Connection recovery and unattended monitoring

`robot watch` runs without interactive input, using saved configuration. It continuously polls hardware, checks AI endpoint/model metadata in a separate thread, and emits full JSON snapshots with health transition events. By default it selects enabled hardware devices and skips simulated devices, as chat does. It never generates AI responses, forwards sensor data to a provider, or sends hardware commands. Reachable metadata does not prove inference speed or successful tool execution.

```powershell
robot watch --device BodyModule
# Finite run and optional latest-status file:
robot watch --device BodyModule --ticks 10 --state-file runtime-health.json
```

Stop with Ctrl+C. On Linux, SIGTERM also closes the monitor cleanly. AI checks start immediately, normally repeat every 15 seconds, and back off after failures up to 300 seconds; successful recovery resets the interval. Use `--ai-interval 5` for a faster bench test. Hardware polling continues during slow/unavailable AI checks. A missing AI configuration is reported as `not_configured`, and does not prevent hardware monitoring. Transition events distinguish states such as waiting, stale, disconnected and recovered; stale sensor data is never marked usable just because USB is connected.

The serial driver retries the configured port after disconnect, clears the old reading on reconnect, and waits for fresh telemetry. If the operating system assigns a different port, update device configuration; RoboClaw does not guess a replacement. The optional status file is replaced atomically and cannot use the robot configuration path. Permissions still govern chat tools; the monitor is a local diagnostic, and does not expose disabled sensor observations to AI.

Chat also has `/health` for current hardware and background AI status. It can start while a previously configured AI endpoint is offline. After connectivity returns, submit a new user message; failed turns are not retried automatically, and no buzzer action is replayed. If a command was acknowledged before a later model-response failure, its printed outcome remains authoritative.

### Raspberry Pi startup service

Install RoboClaw and configure devices/AI on the Pi first. Keep the virtual environment in a stable path, and configure the Pi's actual serial path rather than copying COM4 from Windows. Where available, a `/dev/serial/by-id/...` path is preferable for reconnecting the same USB board. The service runs as your normal user, which must have permission to open that serial device.

Generate the user service **on the Pi from its virtual environment** so the Python and configuration paths match that machine:

```bash
.venv/bin/robot service --device BodyModule --output "$HOME/.config/systemd/user/roboclaw-monitor.service"
systemctl --user daemon-reload
systemctl --user enable --now roboclaw-monitor.service
journalctl --user -u roboclaw-monitor.service -f
```

The generator refuses to overwrite an existing unit and does not enable it implicitly. To regenerate, stop the service and move the old unit aside before generating another. The unit starts the read-only monitor, restarts after process failure, and has no interactive setup or login prompts. It can start before the remote model PC is online and recover later. To start the user service at boot and keep it running after logout, enable user lingering using `sudo loginctl enable-linger "$USER"`. See [systemd user lingering](https://www.freedesktop.org/software/systemd/man/latest/loginctl.html) and [service restart behavior](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html).

Only one process should own the serial port. Stop the monitor before using chat, mood, inspect or another serial session:

```bash
systemctl --user stop roboclaw-monitor.service
.venv/bin/robot chat --device BodyModule --debug
# After leaving chat:
systemctl --user start roboclaw-monitor.service
```

The service does not inherit API keys exported in a separate terminal. If using a hosted provider, configure its key in the user service environment before starting it; never commit keys to the unit or repository. Tailscale must already be installed, signed in and allowed to connect on both hosts; the monitor never installs software, changes firewall rules or authenticates unattended. Windows can run `robot watch` directly; generated systemd units target Linux only.

### Add a head light sensor and illumination output

For the bare photoresistor on GPIO1 and test LED on GPIO5, use the [BB8-v2.2 firmware and wiring guide](firmware/BB8-v2.2/README.md). Flash its HeadModule6 and BodyModule6 sketches; then run `robot hardware setup BodyModule`. This detects firmware-supported features, offers enable/disable choices and saves them into the existing bridge configuration. Normal robot setup also offers feature detection for BB8 bridges.

```powershell
robot light BodyModule
robot illumination BodyModule on
robot illumination BodyModule off
robot capabilities list
robot chat --device BodyModule --debug
```

The light percentage is relative ADC scale, not calibrated lux. `light_usable` evaluates its freshness independently of LiDAR. `illumination_state_usable` marks fresh reported GPIO state; acknowledgment confirms head processing, not physical light output. New AI action `set_illumination` honors global/per-device permissions and the same one-output-per-turn bound as buzzer control. No automatic dark-triggered output is enabled. Existing v2.1 installations continue to support LiDAR and buzzer; light/illumination stay unavailable until firmware advertises them and you enable the extensions.

### Local darkness behavior (no firmware update)

RoboClaw can now react to fresh sensor readings without a chat prompt or AI connection.
This first host-side behavior uses the configured ambient sensor and GPIO5 illumination
output. It is separate from AI tool permissions and from future IR/eye-ring outputs.
Stop chat, watch and other serial sessions before running it.

Preview decisions without changing the LED:

```powershell
.\.venv\Scripts\robot.exe behavior BodyModule
```

Explicitly allow automatic illumination for this session:

```powershell
.\.venv\Scripts\robot.exe behavior BodyModule --allow-illumination
```

Defaults: turn on after relative brightness stays at or below 20% for 2 seconds;
turn off after it stays at or above 35% for 2 seconds; at least 10 seconds between
requests. Customize with `--dark`, `--bright`, `--hold`, and `--cooldown`.
These are relative ADC percentages, not lux; tune them using your own room readings.
Keep the sensor out of the LED's direct light to avoid feedback cycling.

Both fresh ambient readings and fresh illumination state are required. Missing or
stale data breaks the settling period and produces no output request. Each sustained
zone permits one request; failures are reported and not retried, including after a
reconnect. A sustained opposite zone permits a new transition. Restarting the command
starts a new session and evaluates current conditions anew. Full observations,
decisions and acknowledgment outcomes are printed as JSON. Ctrl+C stops the loop;
it does not change the LED's last commanded state. This behavior requires the host
process to keep running and is not an ESP32 firmware automatic-light mode.

Hardware roadmap: camera observations, separate IR illumination and RGB eye output,
body IMU observations, then configurable personality/curiosity. Gas sensor support
will depend on the specific sensor and what gas it measures.
