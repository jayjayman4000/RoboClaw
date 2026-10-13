import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from robot_platform.drivers import registry
from robot_platform.vision_driver import VisionDriver


def payload(frame=1, attention=1, session="session-a", candidates=None):
    return {
        "schema_version": 1,
        "session_id": session,
        "frame_sequence": frame,
        "attention_sequence": attention,
        "state": "awaiting_selection",
        "target": None,
        "candidates": candidates if candidates is not None else [
            {"candidate_id": 7, "x": 0.25, "y": 0.5,
             "box": [100, 120, 60, 80], "frames": 4,
             "priority": 0.42, "expires_in_s": 4.5}
        ],
        "camera_motion": {"status": "valid"},
        "processing_fps": 28.4,
    }


class Server:
    def __init__(self):
        self.value = payload()
        self.posts = []
        self.reject_status = None
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != "/observations":
                    self.send_error(404)
                    return
                body = json.dumps(outer.value).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                if self.path != "/select_target":
                    self.send_error(404)
                    return
                body = self.rfile.read(int(self.headers["Content-Length"]))
                request = json.loads(body)
                outer.posts.append(request)
                if outer.reject_status:
                    response = {"acknowledged": False, "status": outer.reject_status}
                    encoded = json.dumps(response).encode()
                    self.send_response(409)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(encoded)))
                    self.end_headers()
                    self.wfile.write(encoded)
                    return
                response = {
                    "acknowledged": True,
                    "request_id": request["request_id"],
                    "session_id": request["session_id"],
                    "selected_candidate_id": request["candidate_id"],
                    "status": "applied",
                }
                encoded = json.dumps(response).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, *_):
                pass

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.http.serve_forever)
        self.thread.start()
        self.endpoint = f"http://127.0.0.1:{self.http.server_port}"

    def close(self):
        self.http.shutdown()
        self.thread.join()
        self.http.server_close()


class VisionDriverTests(unittest.TestCase):
    def setUp(self):
        self.server = Server()
        self.now = 0.0
        self.driver = VisionDriver(
            {"name": "Vision", "endpoint": self.server.endpoint,
             "timeout_s": 0.5, "stale_after_s": 1.0},
            clock=lambda: self.now,
        )

    def tearDown(self):
        self.server.close()

    def test_valid_observation_is_bounded_and_normalized(self):
        value = self.driver.observe()
        self.assertTrue(value["usable"])
        self.assertEqual(value["observation_type"], "visual_attention")
        self.assertEqual(value["session_id"], "session-a")
        self.assertEqual(value["candidates"][0]["candidate_id"], 7)
        self.assertNotIn("arbitrary", value)
        self.assertEqual(value["health"], "ok")

    def test_frozen_sequence_and_transport_failure_are_unusable(self):
        self.assertTrue(self.driver.observe()["usable"])
        self.now = 1.1
        frozen = self.driver.observe()
        self.assertFalse(frozen["usable"])
        self.assertEqual(frozen["health"], "stale")
        self.server.close()
        self.server = Server.__new__(Server)
        self.server.close = lambda: None
        failed = self.driver.observe()
        self.assertFalse(failed["usable"])
        self.assertEqual(failed["health"], "unavailable")

    def test_invalid_payload_never_remains_usable(self):
        self.assertTrue(self.driver.observe()["usable"])
        self.server.value = {"schema_version": 99}
        value = self.driver.observe()
        self.assertFalse(value["usable"])
        self.assertEqual(value["health"], "invalid")

    def test_selection_validates_fresh_session_and_candidate(self):
        self.assertTrue(self.driver.observe()["usable"])
        for action in [
            {"action": "move", "candidate_id": 7, "session_id": "session-a"},
            {"action": "select_target", "candidate_id": True, "session_id": "session-a"},
            {"action": "select_target", "candidate_id": 8, "session_id": "session-a"},
            {"action": "select_target", "candidate_id": 7, "session_id": "old"},
            {"action": "select_target", "candidate_id": 7, "session_id": "session-a", "extra": 1},
        ]:
            with self.assertRaises(ValueError):
                self.driver.command(action)
        self.assertEqual(self.server.posts, [])

    def test_valid_selection_posts_once_and_matches_acknowledgment(self):
        self.driver.observe()
        result = self.driver.command({
            "action": "select_target", "session_id": "session-a", "candidate_id": 7
        })
        self.assertTrue(result["acknowledged"])
        self.assertEqual(result["selected_candidate_id"], 7)
        self.assertEqual(len(self.server.posts), 1)
        self.assertEqual(set(self.server.posts[0]), {"session_id", "candidate_id", "request_id"})

    def test_same_session_sequence_must_strictly_increase(self):
        self.server.value = payload(frame=10)
        self.assertTrue(self.driver.observe()["usable"])
        self.server.value = payload(frame=9)
        value = self.driver.observe()
        self.assertFalse(value["usable"])
        self.assertEqual(value["health"], "invalid")
        self.server.value = payload(frame=10)
        self.assertFalse(self.driver.observe()["usable"])

    def test_same_session_attention_sequence_cannot_roll_back(self):
        self.server.value = payload(frame=10, attention=5)
        self.assertTrue(self.driver.observe()["usable"])
        self.server.value = payload(frame=11, attention=4)
        value = self.driver.observe()
        self.assertFalse(value["usable"])
        self.assertEqual(value["health"], "invalid")
        self.server.value = payload(frame=12, attention=6)
        self.assertFalse(self.driver.observe()["usable"])

    def test_attention_cannot_change_without_frame_progress(self):
        self.server.value = payload(frame=10, attention=5)
        self.assertTrue(self.driver.observe()["usable"])
        self.server.value = payload(frame=10, attention=6)
        value = self.driver.observe()
        self.assertFalse(value["usable"])
        self.assertEqual(value["health"], "invalid")
        self.server.value = payload(frame=11, attention=7)
        self.assertFalse(self.driver.observe()["usable"])

    def test_selection_rejects_old_cached_observation(self):
        self.driver.observe()
        self.now = 1.1
        with self.assertRaises(ValueError):
            self.driver.command({"action":"select_target","session_id":"session-a","candidate_id":7})
        self.assertEqual(self.server.posts, [])

    def test_deterministic_409_is_not_reported_as_unknown(self):
        self.driver.observe()
        self.server.reject_status = "stale_candidate"
        result = self.driver.command({"action":"select_target","session_id":"session-a","candidate_id":7})
        self.assertFalse(result["acknowledged"])
        self.assertEqual(result["status"], "stale_candidate")

    def test_builtin_registry_exposes_sensor_capability(self):
        cls = registry()["bb8-vision"]
        self.assertEqual(cls.kind, "sensor")
        self.assertTrue(cls.capabilities["target_selection"])


if __name__ == "__main__":
    unittest.main()
