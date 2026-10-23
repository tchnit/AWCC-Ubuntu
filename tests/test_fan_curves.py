from __future__ import annotations

import unittest

from awcc_linux.fan_curves import (
    FAN_MODES_BY_KEY,
    CurvePoint,
    FanCurve,
    decide_curve_output,
)


class FanCurveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.curve = FanCurve((CurvePoint(40, 20), CurvePoint(60, 60), CurvePoint(80, 100)))

    def test_linear_interpolation_and_clamping(self) -> None:
        self.assertEqual(self.curve.target(20), 20)
        self.assertEqual(self.curve.target(50), 40)
        self.assertEqual(self.curve.target(90), 100)

    def test_hysteresis_holds_on_small_temperature_drop(self) -> None:
        self.assertEqual(self.curve.target_with_hysteresis(58, 60, 60), 60)
        self.assertEqual(self.curve.target_with_hysteresis(55, 60, 60), 50)

    def test_capability_gate_never_claims_write(self) -> None:
        result = decide_curve_output(self.curve, 70, 0.2, False)
        self.assertEqual(result.requested_duty, 80)
        self.assertFalse(result.may_write)
        self.assertIn("Capability gate", result.reason)

    def test_stale_sensor_requests_failsafe_only_when_backend_is_verified(self) -> None:
        result = decide_curve_output(self.curve, 50, 6, True)
        self.assertEqual(result.requested_duty, 100)
        self.assertTrue(result.may_write)
        self.assertTrue(result.emergency)

    def test_hot_sensor_requests_failsafe(self) -> None:
        result = decide_curve_output(self.curve, 92, 0.1, True)
        self.assertEqual(result.requested_duty, 100)
        self.assertTrue(result.may_write)
        self.assertTrue(result.emergency)

    def test_builtin_modes_are_complete(self) -> None:
        self.assertEqual(
            set(FAN_MODES_BY_KEY),
            {"auto", "silent", "balanced", "performance", "gaming", "custom"},
        )
        self.assertIsNone(FAN_MODES_BY_KEY["auto"].curve)
        self.assertTrue(all(FAN_MODES_BY_KEY[key].curve for key in set(FAN_MODES_BY_KEY) - {"auto"}))


if __name__ == "__main__":
    unittest.main()
