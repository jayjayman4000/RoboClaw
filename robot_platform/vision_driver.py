"""Bounded HTTP bridge to BB8's local visual-attention process."""
import json
import math
import time
import uuid
import urllib.error
import urllib.request
from urllib.parse import urlsplit


MAX_RESPONSE_BYTES = 65536
MAX_CANDIDATES = 8


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _finite(value, low, high, name):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"Invalid {name}")
    return value


def _endpoint(value):
    parsed = urlsplit(str(value))
    if parsed.scheme != "http" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Vision endpoint must be a plain loopback HTTP origin")
    if parsed.hostname not in ("127.0.0.1", "localhost", "::1") or not parsed.port:
        raise ValueError("Vision endpoint must use loopback with an explicit port")
    if parsed.path not in ("", "/"):
        raise ValueError("Vision endpoint cannot contain a path")
    return f"http://{parsed.netloc}"


def _candidate(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid vision candidate")
    candidate_id = value.get("candidate_id")
    if type(candidate_id) is not int or candidate_id < 1:
        raise ValueError("Invalid candidate_id")
    x = _finite(value.get("x"), 0, 1, "candidate x")
    y = _finite(value.get("y"), 0, 1, "candidate y")
    box = value.get("box")
    if (not isinstance(box, list) or len(box) != 4 or
            any(type(item) is not int for item in box) or
            box[0] < 0 or box[1] < 0 or box[2] < 1 or box[3] < 1):
        raise ValueError("Invalid candidate box")
    frames = value.get("frames")
    if type(frames) is not int or not 1 <= frames <= 1000000:
        raise ValueError("Invalid candidate frames")
    return {
        "candidate_id": candidate_id,
        "x": round(float(x), 4),
        "y": round(float(y), 4),
        "box": box,
        "frames": frames,
        "priority": round(float(_finite(value.get("priority"), 0, 1000, "candidate priority")), 4),
        "expires_in_s": round(float(_finite(value.get("expires_in_s"), 0, 30, "candidate expiry")), 3),
    }


def _target(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Invalid vision target")
    candidate_id = value.get("candidate_id")
    if type(candidate_id) is not int or candidate_id < 1:
        raise ValueError("Invalid target candidate_id")
    x = _finite(value.get("x"), 0, 1, "target x")
    y = _finite(value.get("y"), 0, 1, "target y")
    state = value.get("state")
    if state not in ("selected", "tracking", "uncertain", "lost"):
        raise ValueError("Invalid target state")
    return {"candidate_id": candidate_id, "x": round(float(x), 4),
            "y": round(float(y), 4), "state": state}


def normalize(payload):
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("Unsupported vision observation schema")
    session = payload.get("session_id")
    if not isinstance(session, str) or not session or len(session) > 128:
        raise ValueError("Invalid vision session")
    frame = payload.get("frame_sequence")
    attention = payload.get("attention_sequence")
    if type(frame) is not int or frame < 0 or type(attention) is not int or attention < 0:
        raise ValueError("Invalid vision sequence")
    state = payload.get("state")
    if state not in ("searching", "awaiting_selection", "selected", "tracking", "uncertain", "lost"):
        raise ValueError("Invalid vision state")
    values = payload.get("candidates")
    if not isinstance(values, list) or len(values) > MAX_CANDIDATES:
        raise ValueError("Invalid vision candidate list")
    candidates = [_candidate(item) for item in values]
    if len({item["candidate_id"] for item in candidates}) != len(candidates):
        raise ValueError("Duplicate candidate_id")
    motion = payload.get("camera_motion")
    if not isinstance(motion, dict) or not isinstance(motion.get("status"), str):
        raise ValueError("Invalid camera motion status")
    fps = _finite(payload.get("processing_fps"), 0, 240, "processing_fps")
    return {
        "source": "hardware",
        "observation_type": "visual_attention",
        "health": "ok",
        "usable": True,
        "schema_version": 1,
        "session_id": session,
        "frame_sequence": frame,
        "attention_sequence": attention,
        "state": state,
        "target": _target(payload.get("target")),
        "candidates": candidates,
        "camera_motion": {"status": motion["status"][:80]},
        "processing_fps": round(float(fps), 2),
        "meaning": "anonymous image-space motion regions; no object or person recognition",
    }


class VisionDriver:
    kind = "sensor"
    simulation = False
    label = "BB8 local visual attention (V6 HTTP)"
    capabilities = {"target_selection": True}
    fields = {
        "endpoint": {"type": "str", "default": "http://127.0.0.1:8084"},
        "timeout_s": {"type": "float", "default": 0.5, "min": 0.05, "max": 5},
        "stale_after_s": {"type": "float", "default": 1.0, "min": 0.1, "max": 10},
    }

    def __init__(self, config, clock=time.monotonic):
        self.config = config
        self.endpoint = _endpoint(config.get("endpoint", "http://127.0.0.1:8084"))
        self.timeout = float(config.get("timeout_s", 0.5))
        self.stale_after = float(config.get("stale_after_s", 1.0))
        _finite(self.timeout, 0.05, 5, "vision timeout")
        _finite(self.stale_after, 0.1, 10, "vision stale threshold")
        self.clock = clock
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        self.last_key = None
        self.last_attention = None
        self.last_advance = None
        self.last_received = None
        self.invalid_session = None
        self.last = None

    def _read_json(self, response):
        length = response.headers.get("Content-Length")
        if length is not None and int(length) > MAX_RESPONSE_BYTES:
            raise ValueError("Vision response too large")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("Vision response too large")
        if "application/json" not in response.headers.get("Content-Type", ""):
            raise ValueError("Vision response is not JSON")
        return json.loads(body)

    def _json(self, request):
        with self.opener.open(request, timeout=self.timeout) as response:
            return self._read_json(response)

    def observe(self):
        try:
            request = urllib.request.Request(self.endpoint + "/observations", method="GET",
                                             headers={"Accept": "application/json"})
            value = normalize(self._json(request))
            now = self.clock()
            key = (value["session_id"], value["frame_sequence"])
            if self.invalid_session == value["session_id"]:
                raise ValueError("Vision frame sequence previously rolled back in this session")
            if self.last_key is None or key[0] != self.last_key[0]:
                self.last_key = key
                self.last_attention = value["attention_sequence"]
                self.last_advance = now
                self.invalid_session = None
            elif self.last_attention is not None and value["attention_sequence"] < self.last_attention:
                self.invalid_session = key[0]
                raise ValueError("Vision attention sequence rolled back")
            elif key[1] == self.last_key[1] and value["attention_sequence"] != self.last_attention:
                self.invalid_session = key[0]
                raise ValueError("Vision attention changed without frame progress")
            elif key[1] < self.last_key[1]:
                self.invalid_session = key[0]
                raise ValueError("Vision frame sequence rolled back")
            elif key[1] > self.last_key[1]:
                self.last_key = key
                self.last_attention = value["attention_sequence"]
                self.last_advance = now
            elif self.last_advance is None or now - self.last_advance > self.stale_after:
                value.update(usable=False, health="stale", error="Vision frame sequence stopped advancing")
            self.last_received = now
            self.last = value
            return dict(value)
        except (OSError, TimeoutError, urllib.error.URLError, urllib.error.HTTPError) as error:
            self.last = None
            return {"source": "hardware", "observation_type": "visual_attention",
                    "health": "unavailable", "usable": False, "error": str(error)}
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self.last = None
            return {"source": "hardware", "observation_type": "visual_attention",
                    "health": "invalid", "usable": False, "error": str(error)}

    def command(self, action):
        if not isinstance(action, dict) or set(action) != {"action", "session_id", "candidate_id"}:
            raise ValueError("Expected only action, session_id and candidate_id")
        if action.get("action") != "select_target":
            raise ValueError("Vision supports only select_target")
        session = action.get("session_id")
        candidate_id = action.get("candidate_id")
        if not isinstance(session, str) or type(candidate_id) is not int:
            raise ValueError("Invalid target selection")
        current = self.last
        if (not current or current.get("usable") is not True or current.get("session_id") != session
                or self.last_received is None or self.clock()-self.last_received > self.stale_after):
            raise ValueError("Vision observation is unavailable or session changed")
        if candidate_id not in {item["candidate_id"] for item in current["candidates"]}:
            raise ValueError("Candidate is no longer selectable")
        request_id = uuid.uuid4().hex
        body = json.dumps({"session_id": session, "candidate_id": candidate_id,
                           "request_id": request_id}, separators=(",", ":")).encode()
        request = urllib.request.Request(
            self.endpoint + "/select_target", data=body, method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            result = self._json(request)
        except urllib.error.HTTPError as error:
            if error.code == 409:
                try:rejection=self._read_json(error)
                except (ValueError,TypeError,json.JSONDecodeError):rejection={}
                status=rejection.get("status") if isinstance(rejection,dict) else None
                if status in ("stale_candidate","selection_busy"):
                    return {"acknowledged":False,"status":status,"request_id":request_id,
                            "session_id":session,"selected_candidate_id":candidate_id}
            return {"acknowledged": False, "status": "outcome_unknown", "error": str(error)}
        except (OSError, TimeoutError, urllib.error.URLError,
                ValueError, TypeError, json.JSONDecodeError) as error:
            return {"acknowledged": False, "status": "outcome_unknown", "error": str(error)}
        acknowledged = (
            isinstance(result, dict) and result.get("acknowledged") is True and
            result.get("request_id") == request_id and result.get("session_id") == session and
            result.get("selected_candidate_id") == candidate_id and result.get("status") == "applied"
        )
        return {"acknowledged": acknowledged, "status": result.get("status", "invalid_response") if isinstance(result, dict) else "invalid_response",
                "request_id": request_id, "session_id": session,
                "selected_candidate_id": candidate_id}

    def close(self):
        pass
