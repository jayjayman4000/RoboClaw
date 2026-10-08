# Host serial telemetry

115200 baud by default, UTF-8 JSON object per newline, maximum 4096 bytes per line.
Other message types and boot text are ignored/counted. No commands are sent.

Legacy body output:

```json
{"type":"telemetry","dist":123.0,"brake":false}
```

`dist` is cm. Sensor validity, signal and age are unknown. Live host traffic cannot
prove the head is getting new readings. Valid positive distances through 1200 cm
are accepted; impossible/initial zero readings are rejected.

v1 host output is supported by the adapter and new telemetry prototypes in
firmware/. Original supplied firmware remains legacy:

```json
{"type":"telemetry","protocol_version":1,"distance_cm":123,"strength":250,"valid":true,"sample_age_ms":35,"brake":false}
```

`distance_cm`: cm, positive and <=1200, or null when invalid.
`strength`: raw optical strength 0..65535 or null if unavailable.
`valid`: required boolean, true only for a valid recent sensor sample.
`sample_age_ms`: required finite nonnegative age of the measurement at body JSON
emission, including its residence in the head and body. For no sample ever, emit
invalid/null distance and age zero. `brake` is reported firmware state, not proof
of actuator braking. Future fields may be added without affecting this parser.

RoboClaw adds elapsed monotonic time since host receipt to reported sample age.
Host receipt is not synchronized sensor capture; USB buffering and wireless
transport delay are not precisely measured. For real control, add sample sequence,
head-link validity, and transport latency accounting as part of the firmware and
control contract. This v1 format is a host boundary, not an ESP-NOW wire format.

Threshold defaults to 1 second and is configurable. All invalid, stale,
unverified, waiting or disconnected observations have `usable: false`.

## Controller identity

Firmware emits hello once per second without a host command or reset.

```json
{"type":"hello","protocol_version":1,"controller_id":"AA:BB:CC:DD:EE:FF","name":"BB8 body bridge","firmware_version":"0.4.0-prototype","capabilities":[{"id":"head_range","kind":"sensor","driver":"tfmini-plus","units":"m"}]}
```

Controller IDs must be stable and capability IDs unique. Advertise only implemented
capabilities; physical presence and measurement validity are runtime states. Host
adds host_supported and commands_enabled; advertisements cannot override them.
Hello does not change telemetry receipt time, sample age or validity. Reconnection
clears identity. Messages are bounded to 4096 bytes. Other controller adapters may
translate their own protocols through validate_manifest; they need not use ESP32
firmware. This bridge supports one TFmini range channel.
