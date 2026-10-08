"""Deterministic offline serial scenarios using the production telemetry parser."""
import json
from .serial_driver import SerialTelemetry


class VirtualPort:
    def __init__(self):
        self.is_open = True
        self.data = b""
        self.unplugged = False

    @property
    def in_waiting(self):
        if self.unplugged:
            raise OSError("Demo: USB disconnected")
        return len(self.data)

    def read(self, count):
        result, self.data = self.data[:count], self.data[count:]
        return result

    def close(self):
        self.is_open = False


def run_demo():
    now = 0.0
    port = VirtualPort()
    driver = SerialTelemetry({"port": "offline-demo", "stale_after_s": 1},
                             serial_factory=lambda *a, **k: port, clock=lambda: now)
    def frame(**values):
        return json.dumps({"type": "telemetry", "protocol_version": 1,
                           "distance_cm": 125, "strength": 300,
                           "valid": True, "sample_age_ms": 0, **values}).encode() + b"\n"
    def state(event):
        return {"simulation": True, "event": event, "scenario_time_s": now,
                "observation": {**driver.observe(), "source": "simulation"}}
    try:
        yield state("connected; waiting for telemetry")
        port.data = b"startup log\n" + frame()[:-1]
        yield state("partial frame; no reading yet")
        port.data = b"\n"
        yield state("complete valid measurement")
        now = .1
        port.data = b"{broken json}\n"
        yield state("malformed frame; last reading retained")
        now = .2
        port.data = frame(distance_cm=None, valid=False)
        yield state("sensor reports invalid measurement")
        now = .3
        port.data = frame(sample_age_ms=2000)
        yield state("USB active; sensor sample stale")
        now = .4
        port.data = frame(distance_cm=90)
        yield state("sensor recovers")
        now = 1.5
        yield state("telemetry timeout")
        port.unplugged = True
        yield state("USB unplugged")
        now = 3.6
        port = VirtualPort()
        yield state("USB reconnected; previous reading cleared")
        port.data = frame(distance_cm=80)
        yield state("fresh measurement after reconnect")
        now = 3.7
        port.data = b'{"type":"telemetry","dist":75}\n'
        yield state("legacy firmware; freshness unverified")
    finally:
        driver.close()


def discovery_demo():
    port = VirtualPort()
    port.data = json.dumps({
        "type": "hello", "protocol_version": 1, "controller_id": "demo-body",
        "name": "BB8 body bridge", "firmware_version": "0.4.0-demo",
        "capabilities": [
            {"id": "head_range", "kind": "sensor", "driver": "tfmini-plus", "units": "m"},
            {"id": "future_ring", "kind": "output", "driver": "neopixel", "units": "rgb"}]}).encode() + b"\n"
    driver = SerialTelemetry({"port": "offline-demo"}, serial_factory=lambda *a, **k: port)
    try:
        observation = driver.observe()
        return {"discovered": observation['controller'] is not None, "simulation": True,
                "source": "simulation", "controller": observation['controller'],
                "note": "Future ring illustrates an unsupported advertisement; no LED driver or command execution."}
    finally:
        driver.close()
