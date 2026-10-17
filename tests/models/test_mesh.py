import unittest
from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np
from UnityPy.enums.VertexFormat import VertexFormat

from pgr_assets.models.mesh import (
    Uv3Layout,
    _normalize_colors,
    _read_influences,
    _read_uvs,
    _read_zones,
    bind_influences,
    read_morphs,
)
from pgr_assets.models.rig import Skin


@dataclass
class FakeHandler:
    m_BoneIndices: list | None
    m_BoneWeights: list | None


def skin(joints, unresolved=()) -> Skin:
    return Skin(
        list(joints),
        np.tile(np.eye(4), (len(joints), 1, 1)),
        unresolved=frozenset(unresolved),
    )


class InfluenceTest(unittest.TestCase):
    def test_half_width_streams_are_padded(self):
        handler = FakeHandler([(1, 2), (3, 4)], [(0.7, 0.3), (0.6, 0.4)])
        joints, weights, _ = _read_influences(handler, 2, "part")
        assert joints is not None and weights is not None
        self.assertTrue(np.array_equal(joints, [[1, 2, 0, 0], [3, 4, 0, 0]]))
        self.assertTrue(np.allclose(weights.sum(axis=1), 1.0))

    def test_rigid_binding_synthesizes_a_single_full_weight(self):
        joints, weights, rigid = _read_influences(
            FakeHandler([(5,), (6,)], None), 2, "part"
        )
        assert joints is not None and weights is not None
        self.assertTrue(np.array_equal(joints, [[5, 0, 0, 0], [6, 0, 0, 0]]))
        self.assertTrue(np.array_equal(weights, [[1, 0, 0, 0], [1, 0, 0, 0]]))
        self.assertTrue(rigid)


class BindInfluencesTest(unittest.TestCase):
    def test_an_index_past_the_joint_list_is_neutralized(self):
        joints, weights = bind_influences(
            np.asarray([[0, 5, 0, 0]], np.uint16),
            np.asarray([[0.5, 0.5, 0.0, 0.0]], np.float32),
            skin([7, 9]),
            "part",
        )
        self.assertTrue(np.array_equal(joints, [[0, 0, 0, 0]]))
        self.assertTrue(np.allclose(weights, [[1.0, 0.0, 0.0, 0.0]]))

    def test_an_unresolved_slot_loses_its_weight_and_the_rest_renormalize(self):
        _, weights = bind_influences(
            np.asarray([[0, 1, 0, 0]], np.uint16),
            np.asarray([[0.25, 0.75, 0.0, 0.0]], np.float32),
            skin([7, 9], unresolved=[1]),
            "part",
        )
        self.assertTrue(np.allclose(weights, [[1.0, 0.0, 0.0, 0.0]]))

    def test_a_vertex_with_no_usable_influence_binds_rigidly_to_joint_zero(self):
        joints, weights = bind_influences(
            np.asarray([[3, 3, 3, 3]], np.uint16),
            np.asarray([[0.25, 0.25, 0.25, 0.25]], np.float32),
            skin([7, 9]),
            "part",
        )
        self.assertTrue(np.array_equal(joints, [[0, 0, 0, 0]]))
        self.assertTrue(np.allclose(weights, [[1.0, 0.0, 0.0, 0.0]]))

    def test_usable_influences_come_back_untouched(self):
        joints = np.asarray([[0, 1, 0, 0]], np.uint16)
        weights = np.asarray([[0.25, 0.75, 0.0, 0.0]], np.float32)
        bound = bind_influences(joints, weights, skin([7, 9]), "part")
        self.assertIs(joints, bound[0])
        self.assertIs(weights, bound[1])


@dataclass
class FakeVector3f:
    x: float
    y: float
    z: float


@dataclass
class FakeVertex:
    index: int
    vertex: FakeVector3f
    normal: FakeVector3f
    tangent: FakeVector3f


@dataclass
class FakeChannel:
    name: str
    nameHash: int
    frameIndex: int
    frameCount: int


@dataclass
class FakeShape:
    firstVertex: int
    vertexCount: int
    hasNormals: bool
    hasTangents: bool


def fake_mesh(channels, shapes, vertices, full):
    return SimpleNamespace(
        m_Name="face",
        m_Shapes=SimpleNamespace(
            channels=channels, shapes=shapes, vertices=vertices, fullWeights=full
        ),
    )


def vertex(index, x=0.0, y=0.0, z=0.0, nz=0.0):
    return FakeVertex(
        index,
        FakeVector3f(x, y, z),
        FakeVector3f(0.0, 0.0, nz),
        FakeVector3f(0.0, 0.0, 0.0),
    )


class MorphTargetTest(unittest.TestCase):
    def test_deltas_are_flipped_into_the_gltf_basis(self):
        mesh = fake_mesh(
            [FakeChannel("eye01", 111, 0, 1)],
            [FakeShape(0, 1, False, False)],
            [vertex(3, z=2.0)],
            [100.0],
        )
        target = read_morphs(mesh, (), "face", 10)[0]
        self.assertEqual(target.positions.tolist(), [[0.0, 0.0, -2.0]])

    def test_the_divisor_is_the_channels_own_full_weight(self):
        # r2kuluomumd019101 authors a 50.0 full weight. A hardcoded 100 renders
        # that channel at half strength and nothing raises.
        mesh = fake_mesh(
            [FakeChannel("pupil01", 111, 0, 1)],
            [FakeShape(0, 1, False, False)],
            [vertex(0)],
            [50.0],
        )
        target = read_morphs(mesh, [25.0], "face", 10)[0]
        self.assertEqual(target.full_weight, 50.0)
        self.assertEqual(target.rest_influence, 0.5)

    def test_a_negative_rest_influence_is_not_clamped(self):
        # r2dubianmd010011 authors -57.73. Clamping would silently change an
        # authored pose.
        mesh = fake_mesh(
            [FakeChannel("eye01", 111, 0, 1)],
            [FakeShape(0, 1, False, False)],
            [vertex(0)],
            [100.0],
        )
        target = read_morphs(mesh, [-57.73], "face", 10)[0]
        self.assertAlmostEqual(target.rest_influence, -0.5773)

    def test_a_multi_frame_channel_keeps_the_strongest_frame(self):
        # r2kuluomumd019101/pupil01 is frameCount 2 at [50.0, 100.0]. Keeping
        # the first frame would emit the half strength shape as the full one.
        mesh = fake_mesh(
            [FakeChannel("pupil01", 111, 0, 2)],
            [FakeShape(0, 1, False, False), FakeShape(1, 1, False, False)],
            [vertex(0, y=1.0), vertex(0, y=9.0)],
            [50.0, 100.0],
        )
        target = read_morphs(mesh, (), "face", 10)[0]
        self.assertEqual(target.full_weight, 100.0)
        self.assertEqual(target.positions.tolist(), [[0.0, 9.0, -0.0]])

    def test_normals_are_zero_filled_when_only_some_shapes_author_them(self):
        # Liv's Eye is 1 of 5. glTF requires every target of a primitive to
        # declare the same attributes, and a shape without normals stores zeros.
        mesh = fake_mesh(
            [FakeChannel("a", 1, 0, 1), FakeChannel("b", 2, 1, 1)],
            [FakeShape(0, 1, True, True), FakeShape(1, 1, False, False)],
            [vertex(0, nz=1.0), vertex(0)],
            [100.0, 100.0],
        )
        targets = read_morphs(mesh, (), "face", 10)
        assert targets[0].normals is not None and targets[1].normals is not None
        # The authored normal is flipped like a position, and the shape that
        # authors none contributes its stored zeros rather than being dropped.
        self.assertEqual(targets[0].normals.tolist(), [[0.0, 0.0, -1.0]])
        self.assertEqual(targets[1].normals.tolist(), [[0.0, 0.0, -0.0]])

    def test_indices_are_sorted_and_deduplicated(self):
        # glTF requires sparse indices to be strictly increasing, and an out of
        # order index is a validator error rather than a visible glitch.
        mesh = fake_mesh(
            [FakeChannel("a", 1, 0, 1)],
            [FakeShape(0, 3, False, False)],
            [vertex(5, y=1.0), vertex(2, y=2.0), vertex(5, y=3.0)],
            [100.0],
        )
        target = read_morphs(mesh, (), "face", 10)[0]
        self.assertEqual(target.indices.tolist(), [2, 5])

    def test_a_shape_with_no_deltas_still_produces_a_target(self):
        # 62 shapes on the roster have vertexCount 0. Skipping one would shift
        # every later target index and rebind every influence track.
        mesh = fake_mesh(
            [FakeChannel("a", 1, 0, 1), FakeChannel("b", 2, 1, 1)],
            [FakeShape(0, 0, False, False), FakeShape(0, 1, False, False)],
            [vertex(4, y=1.0)],
            [100.0, 100.0],
        )
        targets = read_morphs(mesh, (), "face", 10)
        self.assertEqual([t.name for t in targets], ["a", "b"])
        self.assertEqual(len(targets[0].indices), 0)


class FakeUVHandler:
    """
    Only the m_UV* attributes _read_uvs touches.
    """

    def __init__(self, **channels):
        for index in range(8):
            setattr(self, f"m_UV{index}", channels.get(f"uv{index}"))


class SmoothNormalChannelTest(unittest.TestCase):
    def test_uv3_stays_a_uv_when_not_requested(self):
        handler = FakeUVHandler(uv0=[(0.25, 0.75)] * 2, uv3=[(0.1, 0.2, 0.3)] * 2)
        uvs, channels, smooth = _read_uvs(handler, 2, "node", Uv3Layout.TEXCOORD)
        self.assertEqual(channels, [0, 3])
        self.assertIsNone(smooth)
        self.assertEqual(uvs[1].shape, (2, 2))

    def test_uv3_leaves_the_uv_list_when_requested(self):
        handler = FakeUVHandler(uv0=[(0.25, 0.75)] * 2, uv3=[(0.1, 0.2, 0.3)] * 2)
        uvs, channels, smooth = _read_uvs(handler, 2, "node", Uv3Layout.SMOOTH_NORMAL)
        self.assertEqual(channels, [0])
        self.assertEqual(len(uvs), 1)
        assert smooth is not None
        self.assertEqual(smooth.shape, (2, 3))

    def test_the_v_flip_is_applied_and_z_is_kept(self):
        handler = FakeUVHandler(uv3=[(0.1, 0.2, 0.3)])
        _, _, smooth = _read_uvs(handler, 1, "node", Uv3Layout.SMOOTH_NORMAL)
        # flip_v is 1 - y and it is the sign the basis flip needs. z is untouched.
        assert smooth is not None
        np.testing.assert_allclose(smooth[0], [0.1, 0.8, 0.3], rtol=0, atol=1e-6)


class ZoneChannelTest(unittest.TestCase):
    def test_a_four_wide_uv1_yields_zones_and_a_two_wide_uv(self):
        handler = FakeUVHandler(uv1=[(0.5, 0.25, 0.875, 0.239), (0.0, 0.0, 0.122, 0.0)])
        uvs, channels, _ = _read_uvs(handler, 2, "node", Uv3Layout.TEXCOORD)
        zones = _read_zones(handler, 2)
        self.assertEqual(channels, [1])
        self.assertEqual(uvs[0].shape, (2, 2))
        assert zones is not None
        self.assertEqual(zones.dtype, np.float32)
        np.testing.assert_array_equal(
            zones, np.array([[0.875, 0.239], [0.122, 0.0]], np.float32)
        )

    def test_a_three_wide_uv1_fills_w_with_one(self):
        handler = FakeUVHandler(uv1=[(0.5, 0.25, 0.373)])
        zones = _read_zones(handler, 1)
        assert zones is not None
        np.testing.assert_array_equal(zones[0], np.array([0.373, 1.0], np.float32))

    def test_a_two_wide_uv1_has_no_zones_and_keeps_its_uv(self):
        handler = FakeUVHandler(uv1=[(0.5, 0.25)])
        _, channels, _ = _read_uvs(handler, 1, "node", Uv3Layout.TEXCOORD)
        self.assertIsNone(_read_zones(handler, 1))
        self.assertEqual(channels, [1])


class ColorFormatTest(unittest.TestCase):
    def test_a_unorm8_stream_comes_out_zero_to_one(self):
        raw = np.array([[0, 128, 255, 255]], np.float32)
        colors = _normalize_colors(raw, VertexFormat.kVertexFormatUNorm8, "node")
        np.testing.assert_allclose(colors[0], [0, 128 / 255, 1, 1], rtol=0, atol=1e-6)


if __name__ == "__main__":
    unittest.main()
