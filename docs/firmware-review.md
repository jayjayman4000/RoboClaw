# Review of supplied HeadModule4 and BodyModule4

Reviewed the supplied `(1).ino` copies. No firmware has been modified, compiled or
flashed in this change. The CLI works with their existing body JSON output.

The head already checks TFmini frame checksums and uses a nonblocking audio engine.
The body bridges ESP-NOW data to newline-delimited JSON, which is a useful host
boundary. The following improvements should precede real motor control:

1. **Report sensor failure and sample age end to end.** Head `loop()` updates
   `myTelemetry` only when `currentDist > 0`, then sends it every 50 ms regardless.
   A disconnected or weak-signal LiDAR therefore leaves the previous distance and
   obstacle flag looking current. Retain strength, mark invalid frames invalid,
   track last valid sample time, and send age/validity. No frame during a loop
   iteration is normal; expire the reading after a deliberate timeout. The body
   must add time since receiving the head packet before emitting sample age.
2. **Add a body timeout.** `lastTelemetryTime` is written but never checked.
   Report head-link loss independently from sensor validity. Once motor control
   exists, implement an explicit local timeout/stop policy. `emergencyBrake` is
   currently only a boolean: it does not stop a motor.
3. **Queue callback work.** Body prints serial JSON and pairs peers inside the
   ESP-NOW receive callback; the sniffer callback also prints. Move processing,
   peer management and all serial output to `loop()` using bounded queues with
   drop counters. Head callbacks should queue mood requests so the audio state
   is owned by `loop()`. Espressif documents WiFi callbacks as high priority and
   recommends queuing work rather than lengthy callback operations.
4. **Set the head radio channel explicitly.** Body sets channel 1; head sets a
   peer's channel but does not set its local radio channel. Set and check the
   same channel on both boards and check initialization/send/peer return codes.
5. **Version the radio packet.** Raw float/bool structs depend on layout and
   padding. Define fixed-width fields with explicit encoding, magic/type/version,
   sample sequence, distance, strength, validity and age. Upgrade both boards
   together. Filter received MACs against an explicitly selected paired peer;
   currently the body accepts any correct-length packet even after pairing.
6. **Make commands exact and bounded.** Body `readStringUntil` can block and uses
   substring matching. Use a bounded, nonblocking line parser and exact command
   fields. Head must ensure `cmd.mood` is null-terminated before `strcmp`. Add
   command IDs and application acknowledgements before relying on execution.
7. **Make WiFi sniffing optional and off by default.** It adds serial traffic and
   callback work unrelated to ranging. WiFi probe RSSI is radio strength, not
   TFmini optical signal strength. RoboClaw ignores these messages.

References: [Espressif ESP-NOW documentation](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/network/esp_now.html).

Recommended next bench test after firmware improvements: unplug the TFmini while
leaving both ESP32s powered, confirm validity expires; turn off the head, confirm
head-link timeout; unplug body USB, confirm host disconnect; reconnect and confirm
no historical reading is presented as fresh. Keep motor power disconnected for
these tests. The firmware's Arduino-ESP32 core version and exact board settings
must be recorded before compiling replacements (the supplied LEDC API is core
version dependent).

## Expansion Wokwi sketch review

Reviewed `wokwi_sim_with_extra_sensors.ino.ino`, `diagram.json` and `libraries.txt`.
This is a separate prototype, not a compatible replacement for HeadModule4 yet.
No simulation run or Arduino compile was performed in this review.

- The expanded `struct_telemetry` is larger than BodyModule4's struct. The body
  rejects it at its exact-length check. Use the versioned head/body protocol
  together before adding these measurements to RoboClaw.
- It substitutes an HC-SR04 ultrasonic sensor for the TFmini. Retain TFmini pins
  17/18 and parser in the real head; make ultrasonic an optional simulation input.
- It prints startup text but no periodic telemetry JSON. The current host driver
  cannot connect directly to this head sketch and receive readings.
- `mpu.begin()` failure prints a warning, but `loop()` still calls `mpu.getEvent()`.
  Store an initialization flag, skip acquisition on failure and report IMU missing.
- `pulseIn(..., 25000)` can block for 25 ms on each loop, delaying audio and LED
  updates. Schedule measurements at a fixed rate and later use edge timing.
- Invalid ultrasonic readings retain old telemetry just like the original head.
  Report invalidity and sample age instead.
- Battery GPIO13 is not connected in the diagram. Mapping raw ADC 0..4095 to
  0..100 produces an arbitrary percentage, not a battery estimate. Report unknown
  until a specified sensing circuit and voltage calibration exist. The scooter
  battery should be measured through a designed sensing circuit, not directly.
- Acceleration and gyro rate are not head orientation. Keep units (m/s² and rad/s)
  explicit; orientation requires estimation and calibration.
- Temperature and gas are raw ADC values, not Celsius or gas concentration. Keep
  them named raw and specify conversion/calibration only when real parts are chosen.
- `setRingColor()` calls `ring.show()` every loop even when color is unchanged.
  Cache the applied color and update only when needed.
- Stepper and A4988 parts are present in the diagram but have no connections or
  firmware control. This sketch does not operate them.
- `libraries.txt` lists Adafruit NeoPixel twice; deduplicate it when packaging.
- Radio channel selection, callback queues, command termination and source checks
  still need the same changes described above.

Next firmware implementation should use one common versioned packet definition
for head and body, preserve TFmini as the physical ranging source, and make every
optional sensor report presence, validity, units and sample age. Add the LED ring
as an output capability rather than bundling it into a generic range sensor.
