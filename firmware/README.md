# ESP32 telemetry prototypes

Matching telemetry-only replacements for Arduino-ESP32 3.x. Both boards must use
these new sketches; original and new radio packets are incompatible. These do not
implement old buzzer moods, WiFi probe sniffing, LED ring, motor or steppers. Keep
original sketches for those features.

1. Select your actual ESP32-S3 board and Arduino-ESP32 3.x core. Record exact core
   version and board options. Enable USB CDC on boot for native USB if required.
   Verify TFmini UART pins 17/18 against your board before wiring. No wiring guide
   is supplied; power and pin compatibility remain board-specific.
2. Compile/flash `HeadBridge/HeadBridge.ino`. Read its printed Head MAC at 115200.
3. Set `HEAD_MAC` in `BodyBridge/BodyBridge.ino`, then compile/flash the body. Default
   zero MAC rejects every sender. Each sketch folder contains identical Protocol.h.
4. Close Serial Monitor. Use `robot discover --port COM5 --save-as BodyV1` with the
   actual body port, enable head_range, and confirm saving. Remove any old bridge
   entry for that port to avoid opening the same port twice.
5. Use `robot run --interval 0.1`. Missing LiDAR frames and missing head radio packets
   must both produce unusable readings. No actuator control is implemented.

USB hello is sent every second with identity and supported range capability. It
advertises driver support, not physical sensor presence. The head sends distance,
strength, validity, age and sample sequence at 20 Hz. The body adds residence time
and invalidates missing head packets. Pre-receipt transport latency is not measured;
age is not a synchronized capture timestamp. Brake is an obstacle flag, not a brake.

Radio channel is explicitly 1. MAC filtering avoids accidental cross-pairing; it
is not authentication. Radio is unencrypted broadcast. Callbacks only copy validated
packets into a queue. Serial output runs in loop(). There is no command handler.

Portable checks: `g++ -std=c++11 tests/protocol_test.cpp -o /tmp/roboclaw-protocol-test`
then `/tmp/roboclaw-protocol-test`. These do not compile the Arduino sketches. No
Arduino toolchain or physical boards were available; board compilation and hardware
checks remain required before use. Keep the two Protocol.h copies identical.

References: [ESP-NOW API](https://docs.espressif.com/projects/esp-idf/en/v5.3.2/esp32/api-reference/network/esp_now.html)
and [TFmini Plus manual](https://en.benewake.com/uploadfiles/2025/04/20250430175221028.pdf).
