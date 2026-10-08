import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from robot_platform.cli import main


class WorkflowTest(unittest.TestCase):
    def test_config_and_simulation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "robot.json"
            def run(*args):
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    main(["--config", str(path), *args])
                return output.getvalue()
            run("init", "bb8")
            run("add", "sensor", "lidar", "--driver", "sim-tfmini")
            run("add", "motor", "drive", "--driver", "sim-motor")
            state = json.loads(run("inspect"))
            self.assertIsNone(state["head_pose"])
            self.assertEqual(state["devices"]["lidar"]["observation"]["measurement"], "single beam")
            before = path.read_bytes()
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                run("add", "sensor", "lidar", "--driver", "sim-camera")
            self.assertEqual(path.read_bytes(), before)
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                run("command", "drive", "set_speed", "--value", "nan")
            run("remove", "lidar")
            self.assertEqual(len(json.loads(path.read_text())["devices"]), 1)


if __name__ == "__main__":
    unittest.main()
