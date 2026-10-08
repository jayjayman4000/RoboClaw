# BB8 head light and illumination firmware v2.2

These sketches extend the user's working HeadModule5/BodyModule5 firmware supplied in BB8-Firmware-v2.1(1).zip. Use these **two sketches**, not the earlier generic HeadBridge/BodyBridge examples.

- Head: `HeadModule6/HeadModule6.ino`
- Body: `BodyModule6/BodyModule6.ino`
- Target: ESP32-S3, Arduino ESP32 core 3.x, with the same board/USB settings used to flash v2.1.
- Existing pins: buzzer GPIO4, TFmini RX GPIO17/TX GPIO18, ESP-NOW channel 1.
- Added pins: photoresistor divider GPIO1 (ADC1), illumination GPIO5 (digital output).

Head wiring: 3.3 V to the photoresistor; its other leg shares a junction with GPIO1 and one end of a 10 kΩ resistor; the other resistor end goes to head GND. GPIO5 feeds a 330 Ω resistor, then the blue LED anode; LED cathode goes to head GND. Use electrically separate breadboard rows for the photoresistor's legs. Disconnect power while wiring. These GPIO numbers must match the ESP32-S3 board's exposed pins.

`ENABLE_LIGHT_SENSOR` and `ENABLE_ILLUMINATION` default to true for this test build. Set a flag false if that component is absent; raw ADC values cannot establish whether a photoresistor is actually connected. Illumination is off at head boot and changes only on an explicit command. It remains in the commanded state until changed or the head resets; losing the host connection does not switch it off. This is a small test LED output, **not** a driver for an IR LED array.

Light sampling averages eight 12-bit ADC reads per 50 ms telemetry cycle with `ADC_11db` attenuation. Larger readings indicate more light with this divider orientation. The raw range is 0–4095 and the percentage is relative ADC scale, not lux; bright readings may saturate before 3.3 V. Calibration to lux and automatic night illumination are not implemented. The LED's own light can affect the sensor, so evaluate ambient readings with illumination off. Arduino ADC reference: https://docs.espressif.com/projects/arduino-esp32/en/latest/api/adc.html

## Flash and test

1. Close chat, watch, Arduino Serial Monitor and other serial programs.
2. Flash HeadModule6 to the **head** board. Flash BodyModule6 to the **body** board. Both files are needed to expose the extensions over USB.
3. Power the head, reconnect the body to the laptop and keep COM4 if Windows still assigns that port.
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

Validation in development uses Python tests plus native C++ builds with mocked Arduino/ESP-NOW APIs to exercise both sketches. This is **not** a complete ESP32 toolchain build or physical hardware validation. Compile and upload both sketches with your Arduino installation, then perform the wiring tests above.
