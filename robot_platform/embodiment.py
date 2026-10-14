"""Machine-readable robot body capabilities exposed to AI clients."""
import json
import math


MAX_MOTIONS = 32
MAX_PARAMETERS = 16
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 512
MAX_UNITS_LENGTH = 32
MIN_DECISION_FRESHNESS_MS = 1
MAX_DECISION_FRESHNESS_MS = 10_000
MIN_DISPATCH_TIMEOUT_MS = 1
MAX_DISPATCH_TIMEOUT_MS = 1_000

_ROOT_FIELDS = {"decision_freshness_ms", "dispatch_timeout_ms", "motions"}
_MOTION_FIELDS = {"description", "interruptible", "parameters"}
_INTERNAL_MOTION_FIELDS = _MOTION_FIELDS | {"driver_action"}
_PARAMETER_FIELDS = {"type", "minimum", "maximum", "units"}
RESERVED_MOTION_PARAMETER_NAMES = frozenset({"action", "deadline_monotonic"})


def _bounded_text(value, maximum):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= maximum


def _finite_number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _normalized_motion_manifest(driver):
    """Return the strict internal manifest, including driver command bindings."""
    capabilities = getattr(driver, "capabilities", {})
    if type(capabilities) is not dict:
        return None
    raw = capabilities.get("motion")
    if getattr(driver, "kind", None) != "motor" or type(raw) is not dict:
        return None
    if set(raw) != _ROOT_FIELDS:
        return None

    freshness = raw["decision_freshness_ms"]
    timeout = raw["dispatch_timeout_ms"]
    motions = raw["motions"]
    if (not _finite_number(freshness)
            or not MIN_DECISION_FRESHNESS_MS <= freshness <= MAX_DECISION_FRESHNESS_MS
            or not _finite_number(timeout)
            or not MIN_DISPATCH_TIMEOUT_MS <= timeout <= MAX_DISPATCH_TIMEOUT_MS
            or type(motions) is not dict
            or not 1 <= len(motions) <= MAX_MOTIONS):
        return None

    normalized_motions = {}
    for name, specification in motions.items():
        if (not _bounded_text(name, MAX_NAME_LENGTH)
                or type(specification) is not dict
                or not _MOTION_FIELDS <= set(specification) <= _INTERNAL_MOTION_FIELDS):
            return None
        description = specification["description"]
        interruptible = specification["interruptible"]
        parameters = specification["parameters"]
        action = specification.get("driver_action", name)
        if (not _bounded_text(description, MAX_DESCRIPTION_LENGTH)
                or type(interruptible) is not bool
                or type(parameters) is not dict
                or len(parameters) > MAX_PARAMETERS
                or not _bounded_text(action, MAX_NAME_LENGTH)):
            return None

        normalized_parameters = {}
        for parameter_name, definition in parameters.items():
            if (not _bounded_text(parameter_name, MAX_NAME_LENGTH)
                    or parameter_name in RESERVED_MOTION_PARAMETER_NAMES
                    or type(definition) is not dict
                    or set(definition) != _PARAMETER_FIELDS
                    or definition["type"] != "number"
                    or not _bounded_text(definition["units"], MAX_UNITS_LENGTH)):
                return None
            minimum = definition["minimum"]
            maximum = definition["maximum"]
            if (not _finite_number(minimum) or not _finite_number(maximum)
                    or minimum > maximum):
                return None
            normalized_parameters[parameter_name] = {
                "type": "number",
                "minimum": minimum,
                "maximum": maximum,
                "units": definition["units"],
            }

        normalized_motions[name] = {
            "description": description,
            "interruptible": interruptible,
            "parameters": normalized_parameters,
            "driver_action": action,
        }

    return {
        "decision_freshness_ms": freshness,
        "dispatch_timeout_ms": timeout,
        "motions": normalized_motions,
    }


def _public_motion_manifest(internal):
    if internal is None:
        return None
    return {
        "decision_freshness_ms": internal["decision_freshness_ms"],
        "dispatch_timeout_ms": internal["dispatch_timeout_ms"],
        "motions": {
            name: {
                "description": specification["description"],
                "interruptible": specification["interruptible"],
                "parameters": {
                    parameter_name: dict(definition)
                    for parameter_name, definition in specification["parameters"].items()
                },
            }
            for name, specification in internal["motions"].items()
        },
    }


def motion_manifest(driver):
    """Return a bounded public manifest, or ``None`` for any schema violation."""
    return _public_motion_manifest(_normalized_motion_manifest(driver))


def manifest_fingerprint(internal):
    return json.dumps(internal, sort_keys=True, separators=(",", ":"), allow_nan=False)


def body_capabilities_with_internal(devices):
    result = {}
    internals = {}
    for name, driver in devices.items():
        internal = _normalized_motion_manifest(driver)
        if internal is None:
            continue
        internals[name] = internal
        result[name] = {"kind": "motor", "motion": _public_motion_manifest(internal)}
    return {"devices": result}, internals


def body_capabilities(devices):
    return body_capabilities_with_internal(devices)[0]


def prepare_motion(driver, name, parameters):
    internal = _normalized_motion_manifest(driver)
    if internal is None or name not in internal["motions"]:
        raise ValueError("Motion is not declared by this device")
    if not isinstance(parameters, dict):
        raise ValueError("Motion parameters must be an object")
    specification = internal["motions"][name]
    definitions = specification["parameters"]
    if set(parameters) != set(definitions):
        raise ValueError("Motion parameters do not match the body capability")
    for key, definition in definitions.items():
        value = parameters[key]
        if not _finite_number(value):
            raise ValueError("Motion parameters must be finite numbers")
        if value < definition["minimum"] or value > definition["maximum"]:
            raise ValueError("Motion parameter is outside the declared body limit")
    return {"action": specification["driver_action"], **parameters}, internal
