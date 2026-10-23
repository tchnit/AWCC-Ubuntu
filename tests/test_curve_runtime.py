from __future__ import annotations

import unittest

from awcc_linux.curve_runtime import CurveSupervisor
from awcc_linux.fan_curves import FAN_MODES_BY_KEY


class FakeActuator:
    def __init__(self) -> None:
        self.duties: list[int] = []
        self.restore_count = 0

    def set_duty(self, duty: int) -> None:
        self.duties.append(duty)

    def restore_automatic(self) -> None:
        self.restore_count += 1


class CurveSupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.actuator = FakeActuator()
        self.runtime = CurveSupervisor(self.actuator, heartbeat_timeout=5)
        self.curve = FAN_MODES_BY_KEY["balanced"].curve
        assert self.curve is not None

    def test_refuses_to_arm_without_verified_takeover(self) -> None:
        with self.assertRaises(RuntimeError):
            self.runtime.arm(False, 0)
        self.assertFalse(self.runtime.status.armed)

    def test_tick_writes_only_after_arm(self) -> None:
        self.runtime.arm(True, 0)
        status = self.runtime.tick(self.curve, 60, 0.1, 1)
        self.assertTrue(status.armed)
        self.assertEqual(self.actuator.duties[-1], self.curve.target(60))

    def test_watchdog_restores_automatic(self) -> None:
        self.runtime.arm(True, 0)
        self.runtime.tick(self.curve, 60, 0.1, 1)
        status = self.runtime.watchdog(7)
        self.assertFalse(status.armed)
        self.assertEqual(self.actuator.restore_count, 1)

    def test_disarm_is_idempotent(self) -> None:
        self.runtime.arm(True, 0)
        self.runtime.disarm()
        self.runtime.disarm()
        self.assertEqual(self.actuator.restore_count, 1)


if __name__ == "__main__":
    unittest.main()
