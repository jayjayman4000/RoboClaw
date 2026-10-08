"""Plugins return observations; simulated actuator commands never reach hardware.

Third-party packages register a Driver class through the entry-point group
robot_platform.drivers. Each class declares kind and accepts device config.
"""
import math
import time
from importlib.metadata import entry_points


class Driver:
    kind = "sensor"
    simulation = False
    fields = {}
    def __init__(self, config):
        self.config = config
    def observe(self):
        raise NotImplementedError
    def close(self):
        pass
    def command(self, action):
        raise ValueError("This device does not accept commands")


class SimCamera(Driver):
    simulation = True
    def observe(self):
        return {"source": "simulation", "scene": "A person stands ahead beside a chair",
                "frame": None, "note": "Synthetic description; no camera image or inference"}


class SimRange(Driver):
    simulation = True
    def observe(self):
        return {"source": "simulation", "distance_m": round(1.5 + .3 * math.sin(time.monotonic()), 3),
                "measurement": "single beam", "frame_id": self.config["name"],
                "head_orientation": None}


class SimMotor(Driver):
    simulation = True
    kind = "motor"
    def __init__(self, config):
        super().__init__(config)
        self.speed = 0.0
    def observe(self):
        return {"source": "simulation", "commanded_speed": self.speed,
                "actual_velocity": None, "units": "normalized"}
    def command(self, action):
        if action.get("action") == "stop":
            self.speed = 0.0
        elif action.get("action") == "set_speed":
            value = float(action["value"])
            if not math.isfinite(value) or not -1 <= value <= 1:
                raise ValueError("Speed must be a finite number between -1 and 1")
            self.speed = value
        else:
            raise ValueError("Supported motor actions: stop, set_speed")
        return {"accepted": True, "simulation_only": True, "commanded_speed": self.speed}


from .serial_driver import SerialTelemetry
from .bb8_bridge import BB8Bridge

BUILTINS = {"bb8-v2": BB8Bridge,"esp32-json": SerialTelemetry, "sim-camera": SimCamera, "sim-tfmini": SimRange, "sim-motor": SimMotor}


def registry():
    result = dict(BUILTINS)
    for entry in entry_points(group="robot_platform.drivers"):
        if entry.name in result:
            raise ValueError(f"Duplicate driver: {entry.name}")
        cls = entry.load()
        if getattr(cls, "kind", None) not in ("sensor", "motor") or not callable(getattr(cls, "observe", None)):
            raise ValueError(f"Invalid driver contract: {entry.name}")
        result[entry.name] = cls
    return result
