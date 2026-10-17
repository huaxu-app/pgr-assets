import unittest

import numpy as np

from pgr_assets.models import coords

QUATERNION = np.array([0.1, 0.2, 0.3, 0.927], np.float64)
TRANSLATION = np.array([1.0, 2.0, 3.0], np.float64)
SCALE = np.array([2.0, 3.0, 4.0], np.float64)
TRIANGLE = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], np.float64)


def trs(quaternion: np.ndarray, translation: np.ndarray, scale: np.ndarray):
    x, y, z, w = quaternion
    rotation = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )
    matrix = np.eye(4)
    matrix[:3, :3] = rotation * scale
    matrix[:3, 3] = translation
    return matrix


def normal_of(triangle: np.ndarray) -> np.ndarray:
    return np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])


class BasisTest(unittest.TestCase):
    def test_conjugation_agrees_with_the_component_flips(self):
        converted = coords.conjugate_matrix(trs(QUATERNION, TRANSLATION, SCALE))
        composed = trs(
            coords.conjugate_quat(QUATERNION), coords.flip_z(TRANSLATION), SCALE
        )
        self.assertTrue(np.allclose(converted, composed))

    def test_conjugation_agrees_with_flipping_the_points(self):
        matrix = trs(QUATERNION, TRANSLATION, SCALE)
        for corner in TRIANGLE:
            point = np.append(corner, 1.0)
            placed = coords.flip_z(matrix @ point)
            converted = coords.conjugate_matrix(matrix) @ coords.flip_z(point)
            self.assertTrue(np.allclose(placed, converted))

    def test_reversed_winding_keeps_the_face_pointing_out(self):
        flipped = coords.flip_z(TRIANGLE)
        reversed_triangle = flipped[
            coords.reverse_winding(np.arange(3, dtype=np.uint32))
        ]
        self.assertTrue(
            np.allclose(
                normal_of(reversed_triangle), coords.flip_z(normal_of(TRIANGLE))
            )
        )


class TextureSpaceTest(unittest.TestCase):
    def test_flipping_v_moves_the_origin_to_the_other_corner(self):
        self.assertTrue(
            np.allclose([[0.0, 1.0]], coords.flip_v(np.array([[0.0, 0.0]])))
        )

    def test_flipping_a_tangent_reflects_xyz_and_keeps_w(self):
        tangent = np.array([[0.8, 0.0, -0.6, 1.0]])
        self.assertTrue(
            np.allclose([[0.8, 0.0, 0.6, 1.0]], coords.flip_tangent(tangent))
        )


if __name__ == "__main__":
    unittest.main()
