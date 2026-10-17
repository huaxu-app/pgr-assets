import unittest

from pgr_assets.models.emission import evaluate_curve, read_flow
from tests.models.test_springs import curve, key


def flow_tree(**overrides) -> dict:
    tree = {
        "UseAnimation": 1,
        "StartFlow": 0.0,
        "Speed": 0.15,
        "ExtendedRange": 1,
        "Curve": curve(key(0.0, 0.0, 1.0, 1.0), key(1.0, 1.0, 1.0, 1.0)),
    }
    tree.update(overrides)
    return tree


class EvaluateTest(unittest.TestCase):
    def test_either_side_of_the_keys_clamps(self):
        ramp = [[0.25, 0.2, 0.0, 0.0], [0.75, 0.6, 0.0, 0.0]]
        self.assertEqual(0.2, evaluate_curve(ramp, 0.0))
        self.assertEqual(0.6, evaluate_curve(ramp, 1.0))

    def test_flat_tangents_ease(self):
        # Hermite with zero slopes is smoothstep, so the midpoint sits at half.
        flat = [[0.0, 0.0, 0.0, 0.0], [1.0, 1.0, 0.0, 0.0]]
        self.assertAlmostEqual(0.5, evaluate_curve(flat, 0.5), places=6)
        self.assertAlmostEqual(0.15625, evaluate_curve(flat, 0.25), places=6)


class ReadFlowTest(unittest.TestCase):
    def test_a_zero_key_curve_falls_back_to_unity_s_linear_default(self):
        tree = flow_tree(Curve=curve())
        self.assertEqual(
            [[0.0, 0.0, 1.0, 1.0], [1.0, 1.0, 1.0, 1.0]], read_flow(tree).curve
        )

    def test_a_zero_extended_range_never_divides_by_zero(self):
        self.assertEqual(1, read_flow(flow_tree(ExtendedRange=0)).extended_range)


class StillTest(unittest.TestCase):
    def test_a_descending_curve_reads_backwards(self):
        tree = flow_tree(
            StartFlow=0.25,
            Curve=curve(key(0.0, 1.0, -1.0, -1.0), key(1.0, 0.0, -1.0, -1.0)),
        )
        self.assertEqual((0.0, 0.75), read_flow(tree).resting_st[1])

    def test_a_start_flow_of_one_wraps_to_zero(self):
        self.assertEqual((0.0, 0.0), read_flow(flow_tree(StartFlow=1.0)).resting_st[1])


if __name__ == "__main__":
    unittest.main()
