import struct
import unittest
from types import SimpleNamespace

import numpy as np

from pgr_assets.models.animation import (
    _bracket,
    _repair,
    decode_clip,
    euler_to_quaternion,
    eval_streamed,
    parse_streamed,
    sample_times,
)
from pgr_assets.models.prefab import Node, measure_depth
from pgr_assets.models.webclip import (
    KEPT,
    PACKED_DIGITS,
    ROTATION_SCALE,
    find_rig_roots,
    find_root_node,
    pack_rotations,
    pack_values,
)

ROOT = np.sqrt(0.5)

POSITION, QUATERNION, SCALE, EULER = 1, 2, 3, 4


def binding(path, attribute):
    return SimpleNamespace(typeID=4, attribute=attribute, path=path)


def clip(bindings, constants, name="Act"):
    """
    A one-frame clip whose curves all come from the constant sub-clip.
    """
    sub = SimpleNamespace(
        m_StreamedClip=SimpleNamespace(curveCount=0, data=[]),
        m_DenseClip=SimpleNamespace(
            m_CurveCount=0,
            m_FrameCount=0,
            m_SampleRate=30.0,
            m_BeginTime=0.0,
            m_SampleArray=[],
        ),
        m_ConstantClip=SimpleNamespace(data=list(constants)),
    )
    return SimpleNamespace(
        m_Name=name,
        m_SampleRate=30.0,
        m_ClipBindingConstant=SimpleNamespace(genericBindings=bindings),
        m_MuscleClip=SimpleNamespace(
            m_StartTime=0.0,
            m_StopTime=0.0,
            m_LoopTime=True,
            m_Clip=SimpleNamespace(data=sub),
        ),
    )


class EulerTest(unittest.TestCase):
    def test_the_order_is_z_then_x_then_y(self):
        # qY(90) * qX(90). Applying x before y would put +0.5 on z.
        quaternion = euler_to_quaternion(np.array([[90.0, 90.0, 0.0]]))
        np.testing.assert_allclose(quaternion, [[0.5, 0.5, -0.5, 0.5]], atol=1e-6)

    def test_an_euler_binding_fills_the_rotation_slot(self):
        decoded = decode_clip(clip([binding(7, EULER)], [90.0, 90.0, 0.0]), {7: 3})
        self.assertEqual(decoded.rotation.nodes.tolist(), [3])
        np.testing.assert_allclose(
            decoded.rotation.values[0], [[0.5, 0.5, -0.5, 0.5]], atol=1e-6
        )

    def test_a_quaternion_on_the_same_node_wins_over_the_euler(self):
        source = clip(
            [binding(7, QUATERNION), binding(7, EULER)],
            [0.0, 0.0, ROOT, ROOT, 90.0, 90.0, 0.0],
        )
        with self.assertLogs("pgr-assets", level="WARNING"):
            decoded = decode_clip(source, {7: 3})
        np.testing.assert_allclose(
            decoded.rotation.values[0], [[0.0, 0.0, ROOT, ROOT]], atol=1e-6
        )


class DegenerateRotationTest(unittest.TestCase):
    def test_an_all_zero_rotation_is_dropped_and_the_rest_survives(self):
        source = clip(
            [binding(7, POSITION), binding(7, QUATERNION), binding(7, SCALE)],
            [1.0, 2.0, 3.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0],
        )
        with self.assertNoLogs("pgr-assets", level="WARNING"):
            decoded = decode_clip(source, {7: 3})
        self.assertEqual(len(decoded.rotation.nodes), 0)
        np.testing.assert_allclose(decoded.translation.values[0], [[1.0, 2.0, 3.0]])
        np.testing.assert_allclose(decoded.scale.values[0], [[1.0, 1.0, 1.0]])


def streamed(*frames, curve_count=8):
    """
    StreamedClip words: per frame its time, a key count, then slot and four
    coefficients per key.
    """
    raw = b""
    for time, keys in frames:
        raw += struct.pack("<fi", time, len(keys))
        for slot, coefficients in keys:
            raw += struct.pack("<i4f", slot, *coefficients)
    words = np.frombuffer(raw, np.uint32).tolist()
    return SimpleNamespace(curveCount=curve_count, data=words)


class StreamedTest(unittest.TestCase):
    def test_a_key_holds_until_the_next_one_starts(self):
        # dx^3 + 2dx + 1 from t=0, then a flat 5 from t=1. Reading the cubic
        # backwards or picking the left segment at t=1 both land on 4.
        keys = parse_streamed(
            streamed(
                (0.0, [(3, (1.0, 0.0, 2.0, 1.0)), (7, (0.0, 0.0, 0.0, 9.0))]),
                (1.0, [(3, (0.0, 0.0, 0.0, 5.0))]),
            ),
            "Act",
        )
        times = np.array([0.0, 0.5, 1.0, 2.0], np.float32)
        curves = eval_streamed(keys, 8, times)
        np.testing.assert_allclose(curves[3], [1.0, 2.125, 5.0, 5.0], rtol=1e-6)
        np.testing.assert_allclose(curves[7], [9.0] * 4)
        np.testing.assert_allclose(curves[5], [0.0] * 4)


class SlotNumberingTest(unittest.TestCase):
    def test_streamed_then_dense_then_constant(self):
        # Slots 0-2 streamed position, 3-4 dense and 5 constant scale, 6-9
        # constant rotation. A sub-clip off by its width puts scale in rotation.
        source = clip(
            [binding(7, POSITION), binding(7, SCALE), binding(7, QUATERNION)],
            [5.0, 0.0, 0.0, ROOT, ROOT],
        )
        source.m_MuscleClip.m_StopTime = 0.1
        sub = source.m_MuscleClip.m_Clip.data
        sub.m_StreamedClip = streamed(
            (
                0.0,
                [(0, (0, 0, 30.0, 0)), (1, (0, 0, 0, 2.0)), (2, (0, 0, 0, 3.0))],
            ),
            curve_count=3,
        )
        sub.m_DenseClip.m_CurveCount = 2
        sub.m_DenseClip.m_FrameCount = 4
        sub.m_DenseClip.m_SampleArray = [1.0, 4.0, 2.0, 4.0, 3.0, 4.0, 4.0, 4.0]
        decoded = decode_clip(source, {7: 3})
        np.testing.assert_allclose(
            decoded.translation.values[0],
            [[0.0, 2.0, 3.0], [1.0, 2.0, 3.0], [2.0, 2.0, 3.0], [3.0, 2.0, 3.0]],
            atol=1e-5,
        )
        np.testing.assert_allclose(
            decoded.scale.values[0],
            [[1.0, 4.0, 5.0], [2.0, 4.0, 5.0], [3.0, 4.0, 5.0], [4.0, 4.0, 5.0]],
        )
        np.testing.assert_allclose(
            decoded.rotation.values[0], [[0.0, 0.0, ROOT, ROOT]] * 4, atol=1e-6
        )


class SampleTimesTest(unittest.TestCase):
    def test_the_grid_ends_on_the_stop_time_and_not_on_the_dense_frame_count(self):
        clip = SimpleNamespace(
            m_Name="Act",
            m_SampleRate=30.0,
            m_MuscleClip=SimpleNamespace(m_StartTime=0.0, m_StopTime=1.0),
        )
        dense = SimpleNamespace(m_SampleRate=30.0, m_BeginTime=0.0, m_FrameCount=32)
        times = sample_times(clip, dense)
        self.assertEqual(31, len(times))
        self.assertAlmostEqual(1.0, float(times[-1]), places=6)


class RepairTest(unittest.TestCase):
    def test_runs_bracket_against_their_neighbors_and_edges_against_one_end(self):
        before, after, fraction = _bracket(
            np.array([False, True, False, False, True, False])
        )
        self.assertEqual([1, 1, 1, 1, 4, 4], before.tolist())
        self.assertEqual([1, 1, 4, 4, 4, 4], after.tolist())
        np.testing.assert_allclose(
            fraction[:, 0], [0.0, 0.0, 1 / 3, 2 / 3, 0.0, 0.0], rtol=1e-6
        )

    def test_a_gap_is_lerped_and_an_edge_run_holds_its_neighbor(self):
        nan = float("nan")
        values = np.array([[nan], [0.0], [nan], [nan], [3.0], [nan]], np.float32)
        with self.assertLogs("pgr-assets", level="WARNING"):
            repaired = _repair(SimpleNamespace(m_Name="Act"), 1, "position", values)
        assert repaired is not None
        np.testing.assert_allclose(
            repaired[:, 0], [0.0, 0.0, 1.0, 2.0, 3.0, 3.0], rtol=1e-6
        )


JOINTS = {4, 5}


def rig():
    """
    A blade dummy at depth 1 that holds no joint, and the rig root at depth 2.
    """
    return [
        Node("target", None, child_count=2),
        Node("Dummy008", 0, child_count=1),
        Node("Bone074", 1),
        Node("Bip001", 0, child_count=1),
        Node("Root", 3, child_count=1),
        Node("Bone001", 4),
    ]


class RigRootsTest(unittest.TestCase):
    def test_only_the_nodes_holding_every_joint_are_admitted(self):
        self.assertEqual(find_rig_roots(rig(), JOINTS), {0, 3, 4})

    def test_a_rig_with_no_joints_admits_every_node(self):
        self.assertEqual(find_rig_roots(rig(), set()), {0, 1, 2, 3, 4, 5})


class RootNodeTest(unittest.TestCase):
    def _root(self, *moving):
        nodes = rig()
        depths = [measure_depth(nodes, node) for node in range(len(nodes))]
        return find_root_node(
            list(moving), depths, find_rig_roots(nodes, JOINTS), set()
        )

    def test_a_shallower_blade_bone_loses_to_the_deeper_rig_root(self):
        self.assertEqual(self._root(1, 4), 4)

    def test_a_blade_bone_alone_leaves_no_root_node(self):
        self.assertIsNone(self._root(2))


def _steps(deltas, components):
    return np.cumsum(np.array(deltas).reshape(components, -1).T, axis=0)


class PackTest(unittest.TestCase):
    def test_a_packed_rotation_comes_back_within_a_tenth_of_a_degree(self):
        rng = np.random.default_rng(7)
        values = np.cumsum(rng.normal(size=(200, 4)) * 0.2, axis=0) + rng.normal(size=4)
        values /= np.linalg.norm(values, axis=1, keepdims=True)

        [deltas], [runs] = pack_rotations(values[None])
        starts = [run["at"] for run in runs]
        components = [run["component"] for run in runs]
        dropped = np.array(components)[
            np.searchsorted(starts, np.arange(200), "right") - 1
        ]
        kept = _steps(deltas, 3) / ROTATION_SCALE
        back = np.zeros((200, 4))
        rows = np.arange(200)
        back[rows[:, None], KEPT[dropped]] = kept
        back[rows, dropped] = np.sqrt(1.0 - (kept**2).sum(axis=1))

        dots = np.abs((back * values).sum(axis=1)).clip(0, 1)
        self.assertLess(np.degrees(2 * np.arccos(dots)).max(), 0.1)

    def test_packed_values_come_back_within_half_a_step(self):
        rng = np.random.default_rng(7)
        values = rng.normal(size=(50, 3)) * [1.0, 30.0, 0.0]

        [deltas] = pack_values(values[None])
        back = _steps(deltas, 3) / 10**PACKED_DIGITS

        self.assertLess(np.abs(back - values).max(), 0.51 / 10**PACKED_DIGITS)


if __name__ == "__main__":
    unittest.main()
