#!/usr/bin/env python3
"""BB8 V6: anonymous candidates selected by RoboClaw; no motor commands."""
import json
import math
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np
from picamera2 import Picamera2
from robot_platform.vision_attention import CandidateRegistry

WIDTH, HEIGHT, FPS = 640, 480, 30
HOST, PORT = "127.0.0.1", 8084
PIXEL_THRESHOLD = 25
MIN_CONTOUR_AREA = 1200
MIN_TARGET_WIDTH = 35
MIN_TARGET_HEIGHT = 35
MATCH_THRESHOLD = 0.68
SEARCH_MARGIN = 90
LOST_AFTER = 0.8
MAX_TEMPLATE_SIZE = 120
JPEG_QUALITY = 75
MIN_FEATURES = 12
MIN_MOTION_FRACTION = 0.012
MAX_REQUEST_BYTES = 1024
SELECTION_APPLY_DEADLINE_S = 0.3

lock = threading.Lock()
stop_event = threading.Event()
latest_jpeg = None
latest_observation = {"schema_version": 1, "state": "starting", "target": None,
                      "candidates": []}
selection_requests = queue.Queue(maxsize=1)

PAGE = """<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BB8 Vision V6</title><style>body{background:#111820;color:#e8edf4;font-family:Arial;text-align:center;margin:20px}
img{width:100%;max-width:960px;border:2px solid #394b5c;border-radius:8px}
pre{text-align:left;max-width:930px;margin:16px auto;padding:15px;background:#202c38;overflow:auto;border-radius:8px}</style></head>
<body><h2>BB8 V6 — RoboClaw-Selected Attention</h2><p>Anonymous motion candidates only. Selection does not move hardware.</p>
<img src="/stream"><pre id="status">Connecting...</pre><script>async function update(){try{const r=await fetch('/observations',{cache:'no-store'});
document.getElementById('status').textContent=JSON.stringify(await r.json(),null,2)}catch(e){document.getElementById('status').textContent='Disconnected'}}
setInterval(update,250);update()</script></body></html>"""


def send_json(handler, status, value):
    body = json.dumps(value, allow_nan=False).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/observations":
            with lock:
                value = dict(latest_observation)
                value["candidates"] = [dict(item) for item in latest_observation.get("candidates", [])]
                value["target"] = dict(latest_observation["target"]) if latest_observation.get("target") else None
            send_json(self, 200, value)
        elif self.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                while not stop_event.is_set():
                    with lock:
                        jpeg = latest_jpeg
                    if jpeg:
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode())
                        self.wfile.write(jpeg + b"\r\n")
                    time.sleep(0.05)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/select_target":
            self.send_error(404)
            return
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if content_type != "application/json" or not 1 <= length <= MAX_REQUEST_BYTES:
            send_json(self, 400, {"acknowledged": False, "status": "invalid_request"})
            return
        try:
            request = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError):
            send_json(self, 400, {"acknowledged": False, "status": "invalid_json"})
            return
        if (not isinstance(request, dict) or set(request) != {"session_id", "candidate_id", "request_id"}
                or not isinstance(request.get("session_id"), str)
                or type(request.get("candidate_id")) is not int
                or not isinstance(request.get("request_id"), str)
                or not 1 <= len(request["request_id"]) <= 128):
            send_json(self, 400, {"acknowledged": False, "status": "invalid_request"})
            return
        with lock:
            current_session = latest_observation.get("session_id")
            candidate_ids = {item.get("candidate_id") for item in latest_observation.get("candidates", [])}
        if request["session_id"] != current_session or request["candidate_id"] not in candidate_ids:
            send_json(self, 409, {"acknowledged": False, "status": "stale_candidate"})
            return
        pending = {**request, "done": threading.Event(), "result": None,
                   "expires_at": time.monotonic() + SELECTION_APPLY_DEADLINE_S}
        try:
            selection_requests.put_nowait(pending)
        except queue.Full:
            send_json(self, 409, {"acknowledged": False, "status": "selection_busy"})
            return
        if not pending["done"].wait(SELECTION_APPLY_DEADLINE_S + 0.1):
            send_json(self, 504, {"acknowledged": False, "status": "outcome_unknown",
                                  "request_id": request["request_id"]})
            return
        send_json(self, 200 if pending["result"].get("acknowledged") else 409, pending["result"])

    def log_message(self, *_):
        pass


def serve():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    server.timeout = 0.5
    print(f"BB8 V6 loopback dashboard: http://{HOST}:{PORT}", flush=True)
    try:
        while not stop_event.is_set():
            server.handle_request()
    finally:
        server.server_close()


def estimate_transform(previous, current):
    points = cv2.goodFeaturesToTrack(previous, maxCorners=250, qualityLevel=0.015,
                                     minDistance=9, blockSize=7)
    if points is None or len(points) < MIN_FEATURES:
        return None, 0, 0.0, "insufficient features"
    tracked, status, _ = cv2.calcOpticalFlowPyrLK(
        previous, current, points, None, winSize=(21, 21), maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 25, 0.01))
    if tracked is None or status is None:
        return None, 0, 0.0, "optical flow failed"
    good = status.reshape(-1) == 1
    src, dst = points[good].reshape(-1, 2), tracked[good].reshape(-1, 2)
    if len(src) < MIN_FEATURES:
        return None, len(src), 0.0, "too few tracked features"
    matrix, inliers = cv2.estimateAffinePartial2D(
        src, dst, method=cv2.RANSAC, ransacReprojThreshold=2.5,
        maxIters=1000, confidence=0.99)
    if matrix is None or inliers is None:
        return None, len(src), 0.0, "RANSAC failed"
    ratio = int(inliers.sum()) / len(src)
    scale = math.hypot(float(matrix[0, 0]), float(matrix[1, 0]))
    rotation = math.degrees(math.atan2(float(matrix[1, 0]), float(matrix[0, 0])))
    if int(inliers.sum()) < MIN_FEATURES or ratio < 0.55 or not (
            0.96 <= scale <= 1.04 and abs(rotation) <= 8
            and abs(float(matrix[0, 2])) <= 55 and abs(float(matrix[1, 2])) <= 55):
        return None, len(src), ratio, "low agreement"
    return matrix, len(src), ratio, "valid"


def compensated_motion(gray, previous):
    if previous is None:
        return None, {"status": "warming up"}
    matrix, features, ratio, status = estimate_transform(previous, gray)
    stats = {"status": status, "tracked_features": features,
             "ransac_inlier_ratio": round(ratio, 3)}
    if matrix is None:
        return None, stats
    aligned = cv2.warpAffine(previous, matrix, (WIDTH, HEIGHT), flags=cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    valid = cv2.warpAffine(np.full_like(previous, 255), matrix, (WIDTH, HEIGHT),
                           flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    valid = cv2.erode(valid, np.ones((3, 3), dtype=np.uint8))
    diff = cv2.absdiff(aligned, gray)
    _, mask = cv2.threshold(diff, PIXEL_THRESHOLD, 255, cv2.THRESH_BINARY)
    mask = cv2.bitwise_and(mask, valid)
    stats.update(dx_pixels=round(float(matrix[0, 2]), 3),
                 dy_pixels=round(float(matrix[1, 2]), 3),
                 rotation_degrees=round(math.degrees(math.atan2(float(matrix[1, 0]), float(matrix[0, 0]))), 3),
                 changed_pixels=cv2.countNonZero(mask))
    return mask, stats


def motion_boxes(mask):
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.dilate(mask, np.ones((13, 13), np.uint8), iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for contour in contours:
        if cv2.contourArea(contour) < MIN_CONTOUR_AREA:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        if w >= MIN_TARGET_WIDTH and h >= MIN_TARGET_HEIGHT:
            boxes.append((x, y, w, h))
    return boxes


def patch_from_box(gray, box):
    x, y, w, h = box
    side = min(w, h, MAX_TEMPLATE_SIZE)
    if side < MIN_TARGET_WIDTH:
        return None, None
    tx = max(0, min(WIDTH - side, x + (w - side) // 2))
    ty = max(0, min(HEIGHT - side, y + (h - side) // 2))
    patch = gray[ty:ty + side, tx:tx + side].copy()
    if patch.std() < 12:
        return None, None
    return (tx, ty, side, side), patch


def motion_strength(mask, box):
    x, y, w, h = box
    return cv2.countNonZero(mask[y:y+h, x:x+w]) / max(1, w * h)


def main():
    global latest_jpeg, latest_observation
    camera = Picamera2()
    camera.configure(camera.create_video_configuration(
        main={"size": (WIDTH, HEIGHT), "format": "RGB888"},
        controls={"FrameRate": FPS}, buffer_count=4))
    registry = CandidateRegistry(ttl_s=5.0, promote_frames=3, max_candidates=8)
    previous = None
    target = None
    target_id = None
    template = None
    last_good = 0.0
    frame_sequence = 0
    fps_count = 0
    fps_start = time.monotonic()
    measured_fps = 0.0
    server_thread = threading.Thread(target=serve, daemon=True)
    try:
        camera.start()
        time.sleep(2)
        server_thread.start()
        print("RoboClaw owns target selection. Camera only; no motors controlled.", flush=True)
        while not stop_event.is_set():
            frame = camera.capture_array()
            gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (5, 5), 0)
            now = time.monotonic()
            mask, camera_stats = compensated_motion(gray, previous)
            state = "searching"
            confidence = None

            if target is not None and template is not None:
                x, y, w, h = target
                tw, th = template.shape[1], template.shape[0]
                sx, sy = max(0, x - SEARCH_MARGIN), max(0, y - SEARCH_MARGIN)
                ex, ey = min(WIDTH, x + w + SEARCH_MARGIN), min(HEIGHT, y + h + SEARCH_MARGIN)
                roi = gray[sy:ey, sx:ex]
                if roi.shape[0] >= th and roi.shape[1] >= tw:
                    result = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
                    _, score, _, point = cv2.minMaxLoc(result)
                    confidence = float(score) if np.isfinite(score) else 0.0
                    if confidence >= MATCH_THRESHOLD:
                        target = (sx + point[0], sy + point[1], tw, th)
                        last_good = now
                        state = "tracking"
                    elif now - last_good < LOST_AFTER:
                        state = "uncertain"
                    else:
                        target = template = None
                        target_id = None
                        state = "lost"
                else:
                    target = template = None
                    target_id = None
                    state = "lost"

            detections = []
            if mask is not None:
                for box in motion_boxes(mask):
                    strength = motion_strength(mask, box)
                    if strength < MIN_MOTION_FRACTION:
                        continue
                    template_box, candidate_template = patch_from_box(gray, box)
                    if template_box is not None:
                        detections.append((template_box, strength, candidate_template))
            registry.update(detections)

            try:
                pending = selection_requests.get_nowait()
            except queue.Empty:
                pending = None
            if pending is not None:
                try:
                    if time.monotonic() > pending["expires_at"]:
                        raise ValueError("Selection request expired before the camera loop applied it")
                    selected = registry.select(pending["session_id"], pending["candidate_id"])
                    if selected.get("template") is None:
                        raise ValueError("Candidate has no usable template")
                    target = selected["box"]
                    template = selected["template"].copy()
                    target_id = selected["candidate_id"]
                    last_good = now
                    state = "selected"
                    pending["result"] = {"acknowledged": True, "status": "applied",
                                         "request_id": pending["request_id"],
                                         "session_id": registry.session_id,
                                         "selected_candidate_id": target_id}
                except ValueError as error:
                    pending["result"] = {"acknowledged": False, "status": "stale_candidate",
                                         "request_id": pending["request_id"], "error": str(error)}
                finally:
                    pending["done"].set()

            candidate_state = registry.observation(WIDTH, HEIGHT)
            candidates = [item for item in candidate_state["candidates"] if item["candidate_id"] != target_id]
            if target is None and candidates and state != "lost":
                state = "awaiting_selection"
            target_observation = None
            if target is not None:
                x, y, w, h = target
                target_observation = {"candidate_id": target_id,
                                      "x": round((x + w / 2) / WIDTH, 4),
                                      "y": round((y + h / 2) / HEIGHT, 4),
                                      "state": state if state in ("selected", "tracking", "uncertain") else "lost"}
                color = (0, 255, 0) if state in ("selected", "tracking") else (0, 200, 255)
                cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
                cv2.putText(frame, f"Selected {target_id} | {state}", (x, max(20, y - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
            for item in candidates:
                x, y, w, h = item["box"]
                cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 255, 0), 1)
                cv2.putText(frame, f"Candidate {item['candidate_id']}", (x, max(12, y - 3)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 0), 1)
            if mask is not None:
                overlay = frame.copy()
                overlay[mask > 0] = (0, 0, 255)
                frame = cv2.addWeighted(frame, 0.85, overlay, 0.15, 0)
            cv2.rectangle(frame, (0, 0), (WIDTH, 38), (20, 28, 36), -1)
            cv2.putText(frame, f"BB8 V6: {state} | RoboClaw selection", (12, 26),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.54, (255, 255, 255), 2)
            ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            frame_sequence += 1
            fps_count += 1
            if now - fps_start >= 1.0:
                measured_fps = fps_count / (now - fps_start)
                fps_count = 0
                fps_start = now
            observation = {"schema_version": 1, "session_id": registry.session_id,
                           "frame_sequence": frame_sequence,
                           "attention_sequence": candidate_state["attention_sequence"],
                           "state": state, "target": target_observation,
                           "candidates": candidates, "camera_motion": camera_stats,
                           "processing_fps": round(measured_fps, 2)}
            with lock:
                latest_observation = observation
                if ok:
                    latest_jpeg = jpg.tobytes()
            previous = gray
    except KeyboardInterrupt:
        print("\nStopping V6...")
    finally:
        stop_event.set()
        camera.stop()
        camera.close()
        server_thread.join(timeout=2)
        print("Camera released.")


if __name__ == "__main__":
    main()
