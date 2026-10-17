"""
Unity to glTF basis change.

Unity is left handed, Y up, +Z forward. glTF is right handed, Y up, +Z toward
the viewer. The change of basis is the reflection `B = diag(1, 1, -1, 1)` in homogeneous form.

Putting a (1, 1, -1) scale on a root node instead imports as a
negative-determinant transform, which breaks skinned rigs in every engine and
inverts inverted-hull outlines. Bake it into the data instead. `B` is its own
inverse and an algebra automorphism, so it collapses to sign flips:

    positions, normals, translations   negate Z
    quaternions (xyzw)                 negate X and Y
    4x4 matrices                       conjugate, B @ M @ B
    triangle indices                   reverse winding, a reflection flips it
    scale                              unchanged

Texture space is a separate convention change, not part of `B`. Unity's UV origin is
bottom-left and glTF's is top-left, so V flips.

**The tangent's handedness sign survives both, because the two flips cancel.** The
reflection alone would invert it, `cross(B N, B T) = det(B) * B (N x T) = -B (N x T)`.
But the bitangent is `dP/dv`, and `v' = 1 - v` reverses that too, so the required
bitangent is `-B (N x T) * w` and the two minus signs meet. Solving
`cross(B N, B T) * w' = -B (N x T) * w` gives `w' = w`.

Every function here is an involution: applying it twice returns the input.
"""

import numpy as np

B = np.diag([1.0, 1.0, -1.0, 1.0])


def flip_z(vectors: np.ndarray) -> np.ndarray:
    flipped = np.array(vectors)
    flipped[..., 2] *= -1.0
    return flipped


def conjugate_quat(quaternions: np.ndarray) -> np.ndarray:
    conjugated = np.array(quaternions)
    conjugated[..., 0] *= -1.0
    conjugated[..., 1] *= -1.0
    return conjugated


def conjugate_matrix(matrices: np.ndarray) -> np.ndarray:
    return B @ np.asarray(matrices, np.float64) @ B


def reverse_winding(indices: np.ndarray) -> np.ndarray:
    return np.asarray(indices).reshape(-1, 3)[:, ::-1].reshape(-1)


def flip_v(uvs: np.ndarray) -> np.ndarray:
    flipped = np.array(uvs)
    flipped[..., 1] = 1.0 - flipped[..., 1]
    return flipped


def flip_tangent(tangents: np.ndarray) -> np.ndarray:
    """
    xyz takes the reflection, w is unchanged. See the module docstring.
    """
    return flip_z(tangents)
