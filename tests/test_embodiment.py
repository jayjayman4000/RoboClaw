from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from robot_platform.agent import Agent, MOTION_OUTCOME_MAX_BYTES, RobotRuntime
from robot_platform.drivers import SimMotor
from robot_platform.embodiment import manifest_fingerprint, motion_manifest, prepare_motion


def motion_permissions(device="drive"):
    return {
        "actions": {"execute_motion": True},
        "devices": {device: {"execute_motion": True}},
    }


def dispatch_runtime_motion(runtime, driver, motion="stop", parameters=None, timeout_ms=100):
    parameters = {} if parameters is None else parameters
    _, manifest = prepare_motion(driver, motion, parameters)
    return runtime.motion(
        "drive",
        motion,
        parameters,
        manifest_fingerprint(manifest),
        timeout_ms,
    )


class MotionDriver:
    kind = "motor"
    simulation = True
    capabilities = {
        "motion": {
            "decision_freshness_ms": 1000,
            "dispatch_timeout_ms": 100,
            "motions": {
                "set_speed": {
                    "description": "Set normalized drive speed",
                    "interruptible": True,
                    "parameters": {
                        "value": {
                            "type": "number",
                            "minimum": -1.0,
                            "maximum": 1.0,
                            "units": "normalized",
                        }
                    },
                },
                "stop": {
                    "description": "Stop drive motion",
                    "interruptible": True,
                    "parameters": {},
                },
            },
        }
    }

    def __init__(self):
        self.calls = []

    def observe(self):
        return {"source": "simulation", "commanded_speed": 0.0}

    def command(self, action):
        self.calls.append(action)
        return {"accepted": True}


class EmbodimentTests(unittest.TestCase):
    def test_agent_turn_resets_prior_motion_authorization(self):
        driver = MotionDriver()
        runtime = RobotRuntime(
            {"drive": driver},
            lambda devices: {
                "simulation": True,
                "devices": {
                    "drive": {"health": "ok", "observation": devices["drive"].observe()}
                },
            },
        )

        class Backend:
            def __init__(self):
                self.responses = iter(
                    [
                        {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "execute_motion",
                                        "arguments": {
                                            "device": "drive",
                                            "motion": "stop",
                                            "parameters": {},
                                        },
                                    }
                                }
                            ],
                        },
                        {"role": "assistant", "content": "not moved", "tool_calls": []},
                    ]
                )

            def complete(self, messages, tools):
                return next(self.responses)

        agent = Agent(
            Backend(),
            runtime,
            trace=lambda line: None,
            permissions=motion_permissions(),
        )
        agent.execute("read_robot_state", {}, [False])

        self.assertEqual(agent.turn("Stop without rereading"), "not moved")
        self.assertEqual(driver.calls, [])

    def test_state_read_authorizes_only_the_returned_target_device(self):
        drive = MotionDriver()
        other = MotionDriver()
        runtime = RobotRuntime(
            {"drive": drive, "other": other},
            lambda devices: {
                "simulation": True,
                "devices": {
                    "other": {
                        "health": "ok",
                        "observation": devices["other"].observe(),
                    }
                },
                "body_pose": None,
                "head_pose": None,
            },
        )
        agent = Agent(None, runtime, permissions=motion_permissions())

        agent.execute("read_robot_state", {}, [False])
        result = agent.execute(
            "execute_motion",
            {"device": "drive", "motion": "stop", "parameters": {}},
            [False],
        )

        self.assertIn("stale", result["error"])
        self.assertEqual(drive.calls, [])

    def test_read_denied_target_never_receives_motion_authorization(self):
        drive = MotionDriver()
        runtime = RobotRuntime(
            {"drive": drive},
            lambda devices: {
                "simulation": True,
                "devices": {
                    "drive": {
                        "health": "ok",
                        "observation": devices["drive"].observe(),
                    }
                },
                "body_pose": None,
                "head_pose": None,
            },
        )
        agent = Agent(
            None,
            runtime,
            permissions={
                "actions": {"execute_motion": True},
                "devices": {
                    "drive": {"read_robot_state": False, "execute_motion": True}
                },
            },
        )

        self.assertIn("error", agent.execute("read_robot_state", {}, [False]))
        result = agent.execute(
            "execute_motion",
            {"device": "drive", "motion": "stop", "parameters": {}},
            [False],
        )

        self.assertIn("stale", result["error"])
        self.assertEqual(drive.calls, [])

    def test_unhealthy_or_explicitly_unusable_target_never_authorizes_motion(self):
        rows = (
            {"health": "disconnected", "observation": {}},
            {"health": "ok", "observation": {"usable": False}},
            {"health": "ok", "observation": {"usable": None}},
        )
        for row in rows:
            with self.subTest(row=row):
                drive = MotionDriver()
                runtime = RobotRuntime(
                    {"drive": drive},
                    lambda devices, current=row: {
                        "simulation": True,
                        "devices": {"drive": deepcopy(current)},
                        "body_pose": None,
                        "head_pose": None,
                    },
                )
                agent = Agent(
                    None,
                    runtime,
                    permissions=motion_permissions(),
                )
                agent.execute("read_robot_state", {}, [False])

                result = agent.execute(
                    "execute_motion",
                    {"device": "drive", "motion": "stop", "parameters": {}},
                    [False],
                )

                self.assertIn("stale", result["error"])
                self.assertEqual(drive.calls, [])

    def test_manifest_change_invalidates_state_authorization(self):
        drive = MotionDriver()
        runtime = RobotRuntime(
            {"drive": drive},
            lambda devices: {
                "simulation": True,
                "devices": {
                    "drive": {"health": "ok", "observation": devices["drive"].observe()}
                },
                "body_pose": None,
                "head_pose": None,
            },
        )
        agent = Agent(None, runtime, permissions=motion_permissions())
        agent.execute("read_robot_state", {}, [False])
        changed = deepcopy(drive.capabilities)
        changed["motion"]["motions"]["stop"]["description"] = "Changed after observation"
        drive.capabilities = changed

        result = agent.execute(
            "execute_motion",
            {"device": "drive", "motion": "stop", "parameters": {}},
            [False],
        )

        self.assertIn("changed", result["error"])
        self.assertEqual(drive.calls, [])

    def test_driver_action_change_invalidates_state_authorization(self):
        drive = MotionDriver()
        manifest = deepcopy(drive.capabilities["motion"])
        manifest["motions"]["stop"]["driver_action"] = "halt"
        drive.capabilities = {"motion": manifest}
        runtime = RobotRuntime(
            {"drive": drive},
            lambda devices: {
                "simulation": True,
                "devices": {
                    "drive": {"health": "ok", "observation": devices["drive"].observe()}
                },
            },
        )
        agent = Agent(None, runtime, permissions=motion_permissions())
        state = agent.execute("read_robot_state", {}, [False])
        self.assertNotIn(
            "driver_action",
            json.dumps(state["body_capabilities"], allow_nan=False),
        )
        changed = deepcopy(drive.capabilities)
        changed["motion"]["motions"]["stop"]["driver_action"] = "coast"
        drive.capabilities = changed

        result = agent.execute(
            "execute_motion",
            {"device": "drive", "motion": "stop", "parameters": {}},
            [False],
        )

        self.assertIn("changed", result["error"])
        self.assertEqual(drive.calls, [])

    def test_manifest_rejects_non_mapping_driver_capabilities(self):
        driver = MotionDriver()
        driver.capabilities = []

        self.assertIsNone(motion_manifest(driver))

    def test_manifest_rejects_nonfinite_missing_reversed_and_extra_fields(self):
        base = deepcopy(MotionDriver.capabilities["motion"])
        invalid = []

        missing_limit = deepcopy(base)
        del missing_limit["motions"]["set_speed"]["parameters"]["value"]["minimum"]
        invalid.append(missing_limit)

        nonfinite_limit = deepcopy(base)
        nonfinite_limit["motions"]["set_speed"]["parameters"]["value"]["maximum"] = float("nan")
        invalid.append(nonfinite_limit)

        reversed_limits = deepcopy(base)
        reversed_limits["motions"]["set_speed"]["parameters"]["value"].update(
            minimum=2.0, maximum=1.0
        )
        invalid.append(reversed_limits)

        extra_root = deepcopy(base)
        extra_root["unsafe"] = True
        invalid.append(extra_root)

        extra_motion = deepcopy(base)
        extra_motion["motions"]["stop"]["duration"] = "forever"
        invalid.append(extra_motion)

        extra_parameter = deepcopy(base)
        extra_parameter["motions"]["set_speed"]["parameters"]["value"]["default"] = 1.0
        invalid.append(extra_parameter)

        unsupported = deepcopy(base)
        unsupported["motions"]["set_speed"]["parameters"]["value"]["type"] = "integer"
        invalid.append(unsupported)

        missing_description = deepcopy(base)
        del missing_description["motions"]["stop"]["description"]
        invalid.append(missing_description)

        wrong_interruptible = deepcopy(base)
        wrong_interruptible["motions"]["stop"]["interruptible"] = 1
        invalid.append(wrong_interruptible)

        for manifest in invalid:
            with self.subTest(manifest=manifest):
                driver = MotionDriver()
                driver.capabilities = {"motion": manifest}
                self.assertIsNone(motion_manifest(driver))

    def test_manifest_rejects_excessive_cardinality_strings_and_deadlines(self):
        base = deepcopy(MotionDriver.capabilities["motion"])
        invalid = []

        too_many_motions = deepcopy(base)
        template = too_many_motions["motions"]["stop"]
        too_many_motions["motions"] = {f"motion_{index}": deepcopy(template) for index in range(33)}
        invalid.append(too_many_motions)

        too_many_parameters = deepcopy(base)
        definition = too_many_parameters["motions"]["set_speed"]["parameters"]["value"]
        too_many_parameters["motions"]["set_speed"]["parameters"] = {
            f"parameter_{index}": deepcopy(definition) for index in range(17)
        }
        invalid.append(too_many_parameters)

        for field, value in (
            ("decision_freshness_ms", 10_001),
            ("dispatch_timeout_ms", 1_001),
            ("decision_freshness_ms", True),
            ("dispatch_timeout_ms", float("inf")),
        ):
            manifest = deepcopy(base)
            manifest[field] = value
            invalid.append(manifest)

        long_motion_name = deepcopy(base)
        long_motion_name["motions"]["m" * 65] = long_motion_name["motions"].pop("stop")
        invalid.append(long_motion_name)

        long_parameter_name = deepcopy(base)
        parameters = long_parameter_name["motions"]["set_speed"]["parameters"]
        parameters["p" * 65] = parameters.pop("value")
        invalid.append(long_parameter_name)

        long_description = deepcopy(base)
        long_description["motions"]["stop"]["description"] = "d" * 513
        invalid.append(long_description)

        empty_units = deepcopy(base)
        empty_units["motions"]["set_speed"]["parameters"]["value"]["units"] = ""
        invalid.append(empty_units)

        for manifest in invalid:
            with self.subTest(manifest=manifest):
                driver = MotionDriver()
                driver.capabilities = {"motion": manifest}
                self.assertIsNone(motion_manifest(driver))

    def test_manifest_rejects_command_envelope_parameter_names(self):
        for reserved_name in ("action", "deadline_monotonic"):
            with self.subTest(reserved_name=reserved_name):
                driver = MotionDriver()
                manifest = deepcopy(driver.capabilities["motion"])
                definition = deepcopy(
                    manifest["motions"]["set_speed"]["parameters"]["value"]
                )
                manifest["motions"]["stop"]["parameters"] = {
                    reserved_name: definition
                }
                driver.capabilities = {"motion": manifest}
                runtime = RobotRuntime(
                    {"drive": driver},
                    lambda devices: {
                        "simulation": True,
                        "devices": {
                            "drive": {
                                "health": "ok",
                                "observation": devices["drive"].observe(),
                            }
                        },
                    },
                )
                agent = Agent(
                    None,
                    runtime,
                    permissions=motion_permissions(),
                )

                self.assertIsNone(motion_manifest(driver))
                self.assertNotIn(
                    "execute_motion",
                    [tool["function"]["name"] for tool in agent.tools],
                )
                result = agent.execute(
                    "execute_motion",
                    {
                        "device": "drive",
                        "motion": "stop",
                        "parameters": {reserved_name: 0},
                    },
                    [False],
                )
                self.assertIn("error", result)
                self.assertEqual(driver.calls, [])

    def test_public_manifest_is_allowlisted_json_and_strips_driver_action(self):
        driver = MotionDriver()
        raw = deepcopy(driver.capabilities["motion"])
        raw["motions"]["stop"]["driver_action"] = "halt"
        driver.capabilities = {"motion": raw}

        public = motion_manifest(driver)

        self.assertEqual(
            set(public), {"decision_freshness_ms", "dispatch_timeout_ms", "motions"}
        )
        self.assertEqual(
            set(public["motions"]["stop"]),
            {"description", "interruptible", "parameters"},
        )
        self.assertNotIn("driver_action", json.dumps(public, allow_nan=False))

    def test_body_description_and_motion_tool_are_capability_gated(self):
        driver = MotionDriver()
        runtime = RobotRuntime(
            {"drive": driver},
            lambda devices: {
                "simulation": True,
                "devices": {
                    "drive": {
                        "health": "ok",
                        "observation": devices["drive"].observe(),
                    }
                },
                "body_pose": None,
                "head_pose": None,
            },
        )

        default_agent = Agent(None, runtime)
        self.assertNotIn(
            "execute_motion",
            [tool["function"]["name"] for tool in default_agent.tools],
        )

        agent = Agent(
            None,
            runtime,
            permissions=motion_permissions(),
        )
        self.assertIn(
            "execute_motion",
            [tool["function"]["name"] for tool in agent.tools],
        )
        state = agent.execute("read_robot_state", {}, [False])
        motion = state["body_capabilities"]["devices"]["drive"]["motion"]
        self.assertEqual(motion["decision_freshness_ms"], 1000)
        self.assertEqual(motion["motions"]["set_speed"]["parameters"]["value"]["maximum"], 1.0)
        self.assertNotIn("driver_action", motion["motions"]["set_speed"])
        self.assertEqual(driver.calls, [])

    def test_motion_requires_fresh_state_and_enforces_declared_limits(self):
        driver = MotionDriver()
        runtime = RobotRuntime(
            {"drive": driver},
            lambda devices: {
                "simulation": True,
                "devices": {"drive": {"health": "ok", "observation": devices["drive"].observe()}},
                "body_pose": None,
                "head_pose": None,
            },
        )
        agent = Agent(None, runtime, permissions=motion_permissions())
        command = {
            "device": "drive",
            "motion": "set_speed",
            "parameters": {"value": 0.4},
        }

        self.assertIn("error", agent.execute("execute_motion", command, [False]))
        self.assertEqual(driver.calls, [])

        agent.execute("read_robot_state", {}, [False])
        result = agent.execute("execute_motion", command, [False])
        self.assertTrue(result["accepted"])
        self.assertEqual(driver.calls[0]["action"], "set_speed")
        self.assertEqual(driver.calls[0]["value"], 0.4)
        self.assertIsInstance(driver.calls[0]["deadline_monotonic"], float)

        agent.execute("read_robot_state", {}, [False])
        invalid = {**command, "parameters": {"value": 1.1}}
        self.assertIn("error", agent.execute("execute_motion", invalid, [False]))
        self.assertEqual(len(driver.calls), 1)

    def test_motion_is_rejected_when_the_ai_decision_uses_stale_state(self):
        driver = MotionDriver()
        runtime = RobotRuntime(
            {"drive": driver},
            lambda devices: {
                "simulation": True,
                "devices": {"drive": {"health": "ok", "observation": devices["drive"].observe()}},
                "body_pose": None,
                "head_pose": None,
            },
        )
        agent = Agent(None, runtime, permissions=motion_permissions())
        command = {"device": "drive", "motion": "stop", "parameters": {}}

        with patch("robot_platform.agent.time.monotonic", side_effect=[10.0, 11.001]):
            agent.execute("read_robot_state", {}, [False])
            result = agent.execute("execute_motion", command, [False])

        self.assertIn("stale", result["error"])
        self.assertEqual(driver.calls, [])

    def test_slow_snapshot_time_consumes_motion_freshness_budget(self):
        driver = MotionDriver()
        sensor = object()
        now = [0.0]

        def slow_snapshot(devices):
            drive_row = {
                "health": "ok",
                "observation": devices["drive"].observe(),
            }
            now[0] = 2.0
            return {
                "simulation": True,
                "devices": {
                    "drive": drive_row,
                    "slow_sensor": {"health": "ok", "observation": {}},
                },
                "body_pose": None,
                "head_pose": None,
            }

        runtime = RobotRuntime({"drive": driver, "slow_sensor": sensor}, slow_snapshot)
        agent = Agent(None, runtime, permissions=motion_permissions())
        command = {"device": "drive", "motion": "stop", "parameters": {}}

        with patch("robot_platform.agent.time.monotonic", side_effect=lambda: now[0]):
            agent.execute("read_robot_state", {}, [False])
            result = agent.execute("execute_motion", command, [False])

        self.assertIn("stale", result["error"])
        self.assertEqual(driver.calls, [])

    def test_manifest_is_revalidated_after_pause_before_dispatch(self):
        driver = MotionDriver()
        initial = deepcopy(driver.capabilities)
        initial["motion"]["motions"]["stop"]["driver_action"] = "old_stop"
        driver.capabilities = initial
        runtime = RobotRuntime(
            {"drive": driver},
            lambda devices: {
                "simulation": True,
                "devices": {
                    "drive": {"health": "ok", "observation": devices["drive"].observe()}
                },
            },
        )
        agent = Agent(None, runtime, permissions=motion_permissions())
        agent.execute("read_robot_state", {}, [False])

        def mutate_manifest(name=None):
            changed = deepcopy(driver.capabilities)
            changed["motion"]["motions"]["stop"]["driver_action"] = "new_stop"
            driver.capabilities = changed

        runtime.behaviors.pause = mutate_manifest
        result = agent.execute(
            "execute_motion",
            {"device": "drive", "motion": "stop", "parameters": {}},
            [False],
        )

        self.assertFalse(result["accepted"])
        self.assertIn("changed", result["error"])
        self.assertEqual(driver.calls, [])

    def test_motion_expires_if_local_dispatch_is_delayed(self):
        driver = MotionDriver()
        runtime = RobotRuntime(
            {"drive": driver},
            lambda devices: {"simulation": True, "devices": {}, "body_pose": None, "head_pose": None},
        )

        with patch("robot_platform.agent.time.monotonic", side_effect=[20.0, 20.101]):
            result = dispatch_runtime_motion(runtime, driver)

        self.assertFalse(result["accepted"])
        self.assertIn("expired", result["error"])
        self.assertEqual(driver.calls, [])

    def test_motion_rechecks_deadline_after_pause_work(self):
        driver = MotionDriver()
        runtime = RobotRuntime(
            {"drive": driver},
            lambda devices: {"simulation": True, "devices": {}},
        )
        now = [20.0]

        def slow_pause(device):
            now[0] = 20.101

        runtime.behaviors.pause = slow_pause
        with patch("robot_platform.agent.time.monotonic", side_effect=lambda: now[0]):
            result = dispatch_runtime_motion(runtime, driver)

        self.assertFalse(result["accepted"])
        self.assertIn("expired", result["error"])
        self.assertEqual(driver.calls, [])

    def test_motion_driver_outcomes_are_bounded_json_safe_or_unknown(self):
        outcomes = (
            {},
            {"accepted": True, "detail": "x" * 3000},
            {"accepted": True, "detail": {"not", "json"}},
            {"accepted": 1},
            {"accepted": True, "value": float("nan")},
        )
        for outcome in outcomes:
            with self.subTest(outcome=outcome):
                driver = MotionDriver()

                def command(action, returned=outcome):
                    driver.calls.append(action)
                    return returned

                driver.command = command
                runtime = RobotRuntime(
                    {"drive": driver},
                    lambda devices: {
                        "simulation": True,
                        "devices": {
                            "drive": {
                                "health": "ok",
                                "observation": devices["drive"].observe(),
                            }
                        },
                    },
                )
                traces = []
                agent = Agent(
                    None,
                    runtime,
                    trace=traces.append,
                    permissions=motion_permissions(),
                )
                agent.execute("read_robot_state", {}, [False])

                result = agent.execute(
                    "execute_motion",
                    {"device": "drive", "motion": "stop", "parameters": {}},
                    [False],
                )

                self.assertIs(result.get("outcome_unknown"), True)
                self.assertIsNot(result.get("accepted"), False)
                self.assertLessEqual(len(json.dumps(result, allow_nan=False).encode()), 512)
                self.assertEqual(len(driver.calls), 1)
                self.assertLessEqual(len(traces[0].encode()), 600)

    def test_motion_outcome_limit_uses_tool_message_json_serialization(self):
        driver = MotionDriver()
        outcome = {
            "accepted": True,
            "a": "x" * 499,
            "b": "x" * 499,
            "c": "x" * 499,
            "d": "x" * 499,
        }
        self.assertEqual(
            len(json.dumps(outcome, separators=(",", ":"), allow_nan=False).encode()),
            2041,
        )
        self.assertEqual(len(json.dumps(outcome, allow_nan=False).encode()), 2050)

        def command(action):
            driver.calls.append(action)
            return outcome

        driver.command = command
        runtime = RobotRuntime({"drive": driver}, lambda devices: {"devices": {}})
        result = dispatch_runtime_motion(runtime, driver)

        self.assertIs(result.get("outcome_unknown"), True)
        self.assertEqual(len(driver.calls), 1)
        self.assertLessEqual(
            len(json.dumps(result, allow_nan=False).encode()),
            MOTION_OUTCOME_MAX_BYTES,
        )

    def test_driver_exception_after_dispatch_reports_unknown_without_retry(self):
        driver = MotionDriver()

        def raising_command(action):
            driver.calls.append(action)
            raise RuntimeError("x" * 10_000)

        driver.command = raising_command
        runtime = RobotRuntime(
            {"drive": driver},
            lambda devices: {
                "simulation": True,
                "devices": {
                    "drive": {"health": "ok", "observation": devices["drive"].observe()}
                },
            },
        )
        traces = []
        agent = Agent(
            None,
            runtime,
            trace=traces.append,
            permissions=motion_permissions(),
        )
        agent.execute("read_robot_state", {}, [False])

        result = agent.execute(
            "execute_motion",
            {"device": "drive", "motion": "stop", "parameters": {}},
            [False],
        )

        self.assertEqual(result.get("outcome_unknown"), True)
        self.assertNotIn("accepted", result)
        self.assertEqual(len(driver.calls), 1)
        json.dumps(result, allow_nan=False)
        self.assertLessEqual(len(traces[0].encode()), 600)

    def test_repeated_motion_within_one_agent_turn_dispatches_once(self):
        driver = MotionDriver()
        runtime = RobotRuntime(
            {"drive": driver},
            lambda devices: {
                "simulation": True,
                "devices": {
                    "drive": {"health": "ok", "observation": devices["drive"].observe()}
                },
            },
        )
        motion_call = {
            "function": {
                "name": "execute_motion",
                "arguments": {"device": "drive", "motion": "stop", "parameters": {}},
            }
        }

        class Backend:
            def __init__(self):
                self.responses = iter(
                    [
                        {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {"function": {"name": "read_robot_state", "arguments": {}}}
                            ],
                        },
                        {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [deepcopy(motion_call), deepcopy(motion_call)],
                        },
                        {"role": "assistant", "content": "done", "tool_calls": []},
                    ]
                )

            def complete(self, messages, tools):
                return next(self.responses)

        agent = Agent(
            Backend(),
            runtime,
            trace=lambda line: None,
            permissions=motion_permissions(),
        )

        self.assertEqual(agent.turn("Stop"), "done")
        self.assertEqual(len(driver.calls), 1)

    def test_builtin_sim_motor_exercises_the_motion_path(self):
        driver = SimMotor({"name": "drive"})
        runtime = RobotRuntime(
            {"drive": driver},
            lambda devices: {
                "simulation": True,
                "devices": {"drive": {"health": "ok", "observation": devices["drive"].observe()}},
                "body_pose": None,
                "head_pose": None,
            },
        )
        agent = Agent(None, runtime, permissions=motion_permissions())

        state = agent.execute("read_robot_state", {}, [False])
        self.assertEqual(
            state["body_capabilities"]["devices"]["drive"]["motion"]["motions"]["set_speed"]["parameters"]["value"]["units"],
            "normalized",
        )
        result = agent.execute(
            "execute_motion",
            {"device": "drive", "motion": "set_speed", "parameters": {"value": -0.25}},
            [False],
        )
        self.assertTrue(result["accepted"])
        self.assertTrue(result["simulation_only"])
        self.assertEqual(driver.observe()["commanded_speed"], -0.25)

    def test_malformed_motion_manifest_never_exposes_physical_tool(self):
        class MalformedMotor:
            kind = "motor"
            capabilities = {"motion": {"motions": {}}}

        runtime = RobotRuntime(
            {"unsafe": MalformedMotor()},
            lambda devices: {"simulation": False, "devices": {}, "body_pose": None, "head_pose": None},
        )
        agent = Agent(None, runtime, permissions=motion_permissions("unsafe"))
        self.assertNotIn(
            "execute_motion",
            [tool["function"]["name"] for tool in agent.tools],
        )

    def test_body_description_respects_per_device_read_permissions(self):
        visible = MotionDriver()
        private = MotionDriver()
        runtime = RobotRuntime(
            {"visible": visible, "private": private},
            lambda devices: {
                "simulation": True,
                "devices": {
                    name: {"health": "ok", "observation": driver.observe()}
                    for name, driver in devices.items()
                },
                "body_pose": None,
                "head_pose": None,
            },
        )
        agent = Agent(
            None,
            runtime,
            permissions={"devices": {"private": {"read_robot_state": False}}},
        )
        state = agent.execute("read_robot_state", {}, [False])
        self.assertEqual(set(state["devices"]), {"visible"})
        self.assertEqual(set(state["body_capabilities"]["devices"]), {"visible"})


if __name__ == "__main__":
    unittest.main()
