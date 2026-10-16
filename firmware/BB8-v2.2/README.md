# BB8 head light and illumination firmware v2.2

These sketches extend the user's working HeadModule5/BodyModule5 firmware supplied in BB8-Firmware-v2.1(1).zip. Use these **two sketches**, not the earlier generic HeadBridge/BodyBridge examples.

- Head: `HeadModule6/HeadModule6.ino`
- Body: `BodyModule6/BodyModule6.ino`
- Target: ESP32-S3 N16R8, Arduino ESP32 core 3.3.7. Each sketch directory has a checked-in PlatformIO environment using `esp32-s3-devkitc1-n16r8`, hardware USB CDC/JTAG mode, and USB CDC at boot so the Raspberry Pi can exchange newline-delimited commands and telemetry over the board's native USB port.
- Existing pins: buzzer GPIO4, TFmini RX GPIO17/TX GPIO18, ESP-NOW channel 1.
- Added pins: photoresistor divider GPIO1 (ADC1), 24-pixel addressable headlamp DIN on GPIO5. The user confirmed the former GPIO5 test-LED role was intentionally repurposed for this ring.

Head wiring: 3.3 V to the photoresistor; its other leg shares a junction with GPIO1 and one end of a 10 kΩ resistor; the other resistor end goes to head GND. Connect the DIYmall ring `DI` signal path to GPIO5. The direct 3.3 V GPIO5 connection has passed the initial powered bench test; for final installation, retain the documented 74AHCT125 level buffer and 330–470 Ω resistor at the first pixel unless further electrical validation supports omitting them. Power the ring from regulated 5 V, share ground with the ESP32, and do not power it from a GPIO or the 3.3 V regulator. Use electrically separate breadboard rows for the photoresistor's legs. Disconnect power while wiring.

`ENABLE_LIGHT_SENSOR` and `ENABLE_ILLUMINATION` default to true. The 24-pixel GRB/800 kHz ring boots dim white at brightness 16/255 (about 90.4 mA LED-only worst-case estimate using the seller's 60 mA/pixel ceiling), then accepts the existing illumination on/off commands. The seller listing conflicts between WS2812B and SK6812; this build assumes the advertised 24-bit RGB protocol, and the delivered pixel type still requires visual bench confirmation. Raw ADC values cannot establish whether a photoresistor is actually connected.

Light sampling averages eight 12-bit ADC reads per 50 ms telemetry cycle with `ADC_11db` attenuation. Larger readings indicate more light with this divider orientation. The raw range is 0–4095 and the percentage is relative ADC scale, not lux; bright readings may saturate before 3.3 V. Calibration to lux and automatic night illumination are not implemented. The LED's own light can affect the sensor, so evaluate ambient readings with illumination off. Arduino ADC reference: https://docs.espressif.com/projects/arduino-esp32/en/latest/api/adc.html

## Flash and test

1. Close chat, watch, Arduino Serial Monitor and other serial programs.
2. Build with `pio run -d BodyModule6` and `pio run -d HeadModule6`. Flash BodyModule6 to the **body** board and HeadModule6 to the **head** board; do not substitute the generic N8 target or omit the USB build flags in each sketch's `platformio.ini`.
3. Power the head, reconnect the body to the Raspberry Pi or laptop, and use the serial port actually assigned by the host.
4. In the RoboClaw project:

```powershell
.\.venv\Scripts\robot.exe hardware setup BodyModule
.\.venv\Scripts\robot.exe light BodyModule
.\.venv\Scripts\robot.exe illumination BodyModule on
.\.venv\Scripts\robot.exe illumination BodyModule off
```

Setup passively detects the features, asks which to enable, asks whether AI may switch illumination, and saves only after confirmation. Existing AI endpoint, port and device permissions are retained. Normal `robot setup` also offers head hardware detection for a configured bb8-v2 bridge. No host code changes or new driver registration are required for these two firmware-supported extensions. Additional component types still require firmware and host support; setup cannot implement an unknown component from its wires alone.

Cover/uncover the photoresistor and check that the reading changes. Then visually confirm the LED turns on and off. Head GPIO acknowledgments do not prove a working LED or illumination. To allow AI output later, use `robot capabilities enable set_illumination --device BodyModule`, subject to any global disable. Restart chat; ask “What is the ambient light level?” and “Turn illumination on/off.” Sensor access uses the existing `read_robot_state` permission.

## Compatible radio extension

The original 24-byte packed packet, magic and version 2 are retained. Telemetry flags add bit 2 (light present), bit 3 (illumination present), and bit 4 (illumination GPIO on). Telemetry reserved bytes 0/1 encode a little-endian 12-bit ADC value; light is sampled immediately before sending. Body `light_age_ms` estimates age from body receipt, so unmeasured over-the-air transit is not included. Host adds serial receipt age and requires a connected head and age no greater than 350 ms; light freshness is independent of LiDAR validity.

Packet type 4 requests illumination; reserved[0] is exactly 0 or 1. Type 5 acknowledges that GPIO command with the same sequence and value. Existing mood commands/type 2 and acknowledgments/type 3 are retained. Body accepts acknowledgments only from its paired head. Serial commands are exact lines `illumination on` / `illumination off`. Old heads have no feature flags and cannot authorize illumination; old bodies ignore the extra telemetry fields. The host writes once, matches command ID plus boolean state, and never retries an ambiguous output.

## Droid-language buzzer extension

The passive piezo on head GPIO4 now has nine fixed, repeatable phrases made only from tones and silent gaps: `hello`, `yes`, `no`, `question`, `acknowledge`, `excited`, `confused`, `warning`, and `goodbye`. The patterns run from the normal `loop()` as a `millis()` state machine; there are no blocking delays. A safety-triggered alarm mood preempts a phrase. While the obstacle flag remains active, the body refuses new phrases and the head independently refuses both phrase and ordinary mood commands, so they cannot silence the alarm.

The Raspberry Pi sends one exact USB serial line to the body, for example `sound hello`. The body validates the name, requires fresh head telemetry advertising `FLAG_SOUND`, sends ESP-NOW packet type 6, and reports `command_sent`. The head validates the phrase ID, starts the local tone sequence, and returns type 7. The body emits `sound_ack` with the original command ID and phrase ID. The Pi matches both fields and never retries an ambiguous command automatically. The body adds a random boot-session value and monotonic command sequence; the head rejects duplicate, out-of-order, and recently retired-session phrase packets, and the body rejects phrase acknowledgments from another session. The original packed packet remains 24 bytes and protocol version 2; telemetry flag bit 5 advertises language support.

After flashing both boards, enable and test from the Pi:

```bash
robot hardware setup BodyModule
robot sound BodyModule hello
robot sound BodyModule question
```

An acknowledgment proves that the head firmware accepted the phrase, not that the buzzer was physically audible. Bench-check all nine phrases with the motors disconnected. This feature assumes the confirmed passive piezo on GPIO4; an active buzzer cannot reproduce the variable pitches.

ESP-NOW remains unencrypted and is not cryptographically authenticated. First-sender MAC locking plus session/sequence checks reduce accidental cross-talk and recorded-packet replay, but they do not stop a nearby active attacker from spoofing a new session. Use only for bench/prototype sound output until fixed MAC allowlists and provisioned ESP-NOW keys are added.

Validation uses the Python suite, native C++ logic builds with mocked Arduino/ESP-NOW APIs, and complete PlatformIO ESP32-S3 builds against Arduino-ESP32 3.3.7. Physical buzzer and radio validation still requires flashing both boards and running the bench checks above.
