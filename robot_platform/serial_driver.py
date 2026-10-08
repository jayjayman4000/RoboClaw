"""Read-only adapter for existing BodyModule4 JSON and future v1 telemetry."""
import json
import math
import time
from datetime import datetime, timezone


def ports():
    from serial.tools.list_ports import comports
    return [{"port": p.device, "description": p.description, "serial_number": p.serial_number,
             "vid": p.vid, "pid": p.pid} for p in comports()]


def numeric(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


class SerialTelemetry:
    kind = "sensor"
    label = "ESP32 body bridge (JSON telemetry, read only)"
    simulation = False
    fields = {"port": {"type": "str", "required": True},
              "baud": {"type": "int", "default": 115200, "min": 1200, "max": 2000000},
              "stale_after_s": {"type": "float", "default": 1.0, "min": .1, "max": 60}}

    def __init__(self, config, serial_factory=None, clock=time.monotonic):
        if serial_factory is None:
            from serial import Serial
            serial_factory = Serial
        self.config, self.factory, self.clock = config, serial_factory, clock
        self.serial = None
        self.buffer = bytearray()
        self.controller = None
        self.latest = None
        self.received = None
        self.received_at = None
        self.last_attempt = -math.inf
        self.error = None
        self.malformed = 0
        self.ignored = 0

    def _accept(self, line):
        try:
            data = json.loads(line)
            if isinstance(data, dict) and data.get("type") == "hello":
                from .discovery import validate_manifest
                self.controller = validate_manifest(data)
                return
            if not isinstance(data, dict) or data.get("type") != "telemetry":
                self.ignored += 1
                return
            version = data.get("protocol_version", 0)
            if type(version) is not int or version not in (0, 1):
                raise ValueError("Unsupported telemetry protocol")
            bb8_v2 = version == 0 and ("sensor_valid" in data or "head_connected" in data)
            if bb8_v2:
                valid, link = data.get("sensor_valid"), data.get("head_connected")
                age, sequence = data.get("sample_age_ms"), data.get("seq")
                overwrites = data.get("rx_overwrites")
                if type(valid) is not bool or type(link) is not bool:
                    raise ValueError("BB8 v2 requires sensor_valid and head_connected")
                if type(sequence) is not int or not 0 <= sequence <= 0xffffffff:
                    raise ValueError("Invalid BB8 radio sequence")
                if type(overwrites) is not int or not 0 <= overwrites <= 0xffffffff:
                    raise ValueError("Invalid BB8 overwrite count")
                if age is not None and (not numeric(age) or age < 0):
                    raise ValueError("Invalid BB8 sample age")
                if valid and (age is None or not link):
                    raise ValueError("Inconsistent BB8 validity")
            else:
                valid, age = data.get("valid"), data.get("sample_age_ms")
                link, sequence = data.get("head_link_valid"), data.get("sample_sequence")
                overwrites = None
            verified = version == 1 or bb8_v2
            distance = data.get("distance_cm", data.get("dist"))
            if not (verified and valid is False and distance is None) and (not numeric(distance) or not 0 < distance <= 1200):
                raise ValueError("Invalid distance")
            strength = data.get("strength")
            if strength is not None and (type(strength) is not int or not 0 <= strength <= 65535):
                raise ValueError("Invalid strength")
            if version == 1:
                if type(valid) is not bool or not numeric(age) or age < 0:
                    raise ValueError("v1 requires valid and sample_age_ms")
            if link is not None and type(link) is not bool:
                raise ValueError("Invalid head link flag")
            if sequence is not None and (type(sequence) is not int or not 0 <= sequence <= 0xffffffff):
                raise ValueError("Invalid sample sequence")
            if verified and link is False:
                valid = False
            if bb8_v2 and valid and (strength is None or strength < 100 or strength == 65535):
                valid = False
            self.latest = {"source": "hardware", "protocol_version": version,
                           "telemetry_schema": "bb8-v2" if bb8_v2 else ("v1" if version == 1 else "legacy"),
                           "rx_overwrites": overwrites,
                           "distance_m": None if distance is None else distance / 100, "strength": strength,
                           "head_link_valid": link, "sample_sequence": sequence,
                           "valid": valid if verified else None,
                           "sample_age_ms": age if verified else None,
                           "obstacle_reported": data.get("brake"), "measurement": "single beam",
                           "head_orientation": None,
                           "freshness_verified": verified,
                           "warning": None if verified else "Legacy firmware: sensor validity, signal strength and sample age unavailable"}
            self.received = self.clock()
            self.received_at = datetime.now(timezone.utc).isoformat()
        except (ValueError, TypeError, UnicodeDecodeError):
            self.malformed += 1

    def observe(self):
        now = self.clock()
        if self.serial is None and now - self.last_attempt >= 2:
            self.last_attempt = now
            try:
                self.serial = self.factory(self.config["port"], int(self.config.get("baud", 115200)), timeout=0)
                self.error = None
                self.buffer.clear()
                self.latest = self.received = self.received_at = None
                self.controller = None
            except Exception as error:
                self.error = str(error)
        if self.serial is not None:
            try:
                if not self.serial.is_open:
                    raise OSError("Serial port closed")
                self.buffer.extend(self.serial.read(min(self.serial.in_waiting, 65536)))
                lines = self.buffer.split(b"\n")
                self.buffer = bytearray(lines.pop())
                for line in lines:
                    if len(line) <= 4096:
                        self._accept(line)
                    else:
                        self.malformed += 1
                if len(self.buffer) > 4096:
                    self.buffer.clear()
                    self.malformed += 1
            except Exception as error:
                self.error = str(error)
                self.close()
        age_s = None if self.received is None else max(0, self.clock() - self.received)
        limit = float(self.config.get("stale_after_s", 1))
        if self.latest and self.latest.get("telemetry_schema") == "bb8-v2":
            limit = min(limit, .350)
        if self.serial is None:
            health = "disconnected"
        elif self.latest is None:
            health = "waiting"
        elif age_s > limit:
            health = "stale"
        elif self.latest["freshness_verified"]:
            if self.latest.get("telemetry_schema") == "bb8-v2" and self.latest.get("head_link_valid") is False:
                health = "head_disconnected"
            elif not self.latest["valid"]:
                health = "invalid"
            else:
                sensor_age = self.latest["sample_age_ms"] / 1000 + age_s
                health = "stale" if sensor_age > limit else "ok"
        else:
            health = "unverified"
        expected = self.config.get("controller", {}).get("controller_id")
        if expected and self.controller and self.controller["controller_id"] != expected:
            health = "identity_mismatch"
        selected = self.config.get("enabled_capabilities")
        if selected is not None and (self.controller is None or not any(
                c["id"] in selected and c["host_supported"] for c in self.controller["capabilities"])):
            if health not in ("disconnected", "waiting"):
                health = "disabled"
        return {**(self.latest or {"source": "hardware", "distance_m": None, "strength": None}),
                "controller": self.controller,
                "enabled_capabilities": self.config.get("enabled_capabilities"),
                "health": health, "connection": "connected" if self.serial else "disconnected",
                "received_at": self.received_at, "received_age_s": age_s,
                "timestamp_basis": "host receipt; not sensor capture time",
                "usable": health == "ok", "port": self.config["port"],
                "error": self.error, "malformed_lines": self.malformed, "ignored_lines": self.ignored}

    def close(self):
        if self.serial is not None:
            try:
                self.serial.close()
            except Exception:
                pass
            self.serial = None

    def command(self, action):
        raise ValueError("Serial telemetry driver is read-only")


def connection_test(config, timeout=5, require_fresh=False):
    driver = SerialTelemetry(config)
    deadline = time.monotonic() + timeout
    reading = None
    try:
        while time.monotonic() < deadline:
            reading = driver.observe()
            if reading.get("received_at") is not None and (not require_fresh or reading.get("usable")):
                return {"passed": True, "fresh_measurement": reading.get("usable", False),
                        "test": "fresh usable telemetry received" if require_fresh else "recognized telemetry received; not sensor validation",
                        "observation": reading}
            time.sleep(.05)
        return {"passed": False, "test": "no fresh usable telemetry before timeout" if require_fresh else "no recognized telemetry before timeout", "observation": reading}
    finally:
        driver.close()
