import unittest

from pgr_assets.models.springs import (
    read_curve_keys,
)
from pgr_assets.models.unity import STEEP


def key(
    time: float = 0.0, value: float = 1.0, in_slope: float = 0.0, out_slope: float = 0.0
) -> dict:
    return {
        "time": time,
        "value": value,
        "inSlope": in_slope,
        "outSlope": out_slope,
        "weightedMode": 0,
        "inWeight": 0.0,
        "outWeight": 0.0,
    }


def curve(*keys: dict) -> dict:
    return {"m_Curve": list(keys)}


class CurveKeysTest(unittest.TestCase):
    def test_a_zero_key_curve_is_a_no_op(self):
        self.assertIsNone(read_curve_keys(curve()))

    def test_a_flat_one_curve_is_a_no_op(self):
        self.assertIsNone(read_curve_keys(curve(key(0.0, 1.0), key(1.0, 1.0))))

    def test_a_varying_curve_keeps_time_value_and_slopes_only(self):
        raw = curve(key(0.0, 1.0), key(1.0, 0.35, -0.9, 0.0))
        self.assertEqual(
            [[0.0, 1.0, 0.0, 0.0], [1.0, 0.35, -0.9, 0.0]], read_curve_keys(raw)
        )

    def test_a_one_valued_curve_with_a_slope_is_not_a_no_op(self):
        # Value 1.0 at both keys but a slope bends the segment between them.
        raw = curve(key(0.0, 1.0, 0.0, 2.0), key(1.0, 1.0))
        self.assertIsNotNone(read_curve_keys(raw))

    def test_a_stepped_key_is_clamped_finite(self):
        raw = curve(key(0.0, 0.5, 0.0, float("inf")), key(1.0, 0.2, float("-inf")))
        self.assertEqual(
            [[0.0, 0.5, 0.0, STEEP], [1.0, 0.2, -STEEP, 0.0]], read_curve_keys(raw)
        )


if __name__ == "__main__":
    unittest.main()
