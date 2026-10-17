"""
Unity's built-in primitive meshes, as they're compiled in, not in a bundle.
"""

from typing import Any, TypedDict

import numpy as np

from pgr_assets.models.mesh import Geometry
from pgr_assets.models.unity import resolve_external_path

BUILTIN_FILE = "unity default resources"

NAMES = {
    10200: "pSphere1",
    10202: "Cube",
    10203: "pCylinder1",
    10204: "pPlane1",
    10205: "polySurface2",
    10206: "Cylinder",
    10207: "Sphere",
    10208: "Capsule",
    10209: "Plane",
    10210: "Quad",
    10211: "Icosphere",
    10212: "icosahedron",
    10213: "pyramid",
}

_CUBE_POSITIONS = (
    (0.5, -0.5, -0.5), (-0.5, -0.5, -0.5), (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5),
    (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5), (0.5, -0.5, 0.5), (-0.5, -0.5, 0.5),
    (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5), (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5),
    (0.5, -0.5, 0.5), (0.5, -0.5, -0.5), (-0.5, -0.5, -0.5), (-0.5, -0.5, 0.5),
    (-0.5, -0.5, -0.5), (-0.5, 0.5, -0.5), (-0.5, 0.5, 0.5), (-0.5, -0.5, 0.5),
    (0.5, -0.5, 0.5), (0.5, 0.5, 0.5), (0.5, 0.5, -0.5), (0.5, -0.5, -0.5),
)
_CUBE_NORMALS = (
    (0, 0, -1), (0, 0, -1), (0, 0, -1), (0, 0, -1),
    (0, 1, 0), (0, 1, 0), (0, 0, 1), (0, 0, 1),
    (0, 1, 0), (0, 1, 0), (0, 0, 1), (0, 0, 1),
    (0, -1, 0), (0, -1, 0), (0, -1, 0), (0, -1, 0),
    (-1, 0, 0), (-1, 0, 0), (-1, 0, 0), (-1, 0, 0),
    (1, 0, 0), (1, 0, 0), (1, 0, 0), (1, 0, 0),
)
_CUBE_TANGENTS = ((-1, 0, 0, -1),) * 16 + ((0, 0, 1, -1),) * 4 + ((0, 0, -1, -1),) * 4
_CUBE_UV0 = (
    (0, 1), (1, 1), (0, 0), (1, 0),
    (0, 0), (1, 0), (0, 0), (1, 0),
    (0, 1), (1, 1), (0, 1), (1, 1),
    (0, 1), (0, 0), (1, 0), (1, 1),
    (0, 1), (0, 0), (1, 0), (1, 1),
    (0, 1), (0, 0), (1, 0), (1, 1),
)
_CUBE_UV1 = (
    (0.690987, 0.652836), (0.996658, 0.652836),
    (0.690987, 0.347164), (0.996658, 0.347164),
    (0.309727, 0.652836), (0.00405577, 0.652836),
    (0.347164, 0.347164), (0.652836, 0.347164),
    (0.309727, 0.347164), (0.00405577, 0.347164),
    (0.347164, 0.652836), (0.652836, 0.652836),
    (0.347164, 0.995944), (0.347164, 0.690273),
    (0.652836, 0.690273), (0.652836, 0.995944),
    (0.690273, 0.690273), (0.995944, 0.690273),
    (0.995944, 0.995944), (0.690273, 0.995944),
    (0.309727, 0.995944), (0.00405577, 0.995944),
    (0.00405577, 0.690273), (0.309727, 0.690273),
)
_CUBE_INDICES = (
    3, 2, 0, 1, 3, 0,
    5, 4, 8, 9, 5, 8,
    7, 6, 10, 11, 7, 10,
    14, 13, 12, 15, 14, 12,
    18, 17, 16, 19, 18, 16,
    22, 21, 20, 23, 22, 20,
)

_QUAD_POSITIONS = (
    (-0.5, -0.5, 3.06162e-17), (0.5, -0.5, 3.06162e-17),
    (-0.5, 0.5, -3.06162e-17), (0.5, 0.5, -3.06162e-17),
)
_QUAD_NORMALS = ((0, 0, 1),) * 4
_QUAD_TANGENTS = ((1, 0, 0, -1),) * 4
_QUAD_UV0 = ((0, 1), (1, 1), (0, 0), (1, 0))
_QUAD_INDICES = (1, 3, 0, 2, 0, 3)

class Baked(TypedDict):
    positions: tuple[tuple[float, float, float], ...]
    normals: tuple[tuple[float, float, float], ...]
    tangents: tuple[tuple[float, float, float, float], ...]
    uvs: tuple[tuple[tuple[float, float], ...], ...]
    uv_channels: tuple[int, ...]
    indices: tuple[int, ...]


BAKED: dict[int, Baked] = {
    10202: {
        "positions": _CUBE_POSITIONS,
        "normals": _CUBE_NORMALS,
        "tangents": _CUBE_TANGENTS,
        "uvs": (_CUBE_UV0, _CUBE_UV1),
        "uv_channels": (0, 1),
        "indices": _CUBE_INDICES,
    },
    10210: {
        "positions": _QUAD_POSITIONS,
        "normals": _QUAD_NORMALS,
        "tangents": _QUAD_TANGENTS,
        "uvs": (_QUAD_UV0,),
        "uv_channels": (0,),
        "indices": _QUAD_INDICES,
    },
}


def resolve_builtin_key(pointer: Any) -> int | None:
    path = resolve_external_path(pointer)
    if path is None or path.rsplit("/", 1)[-1].lower() != BUILTIN_FILE:
        return None
    return pointer.m_PathID


def read_builtin_geometry(path_id: int, name: str) -> Geometry | None:
    baked = BAKED.get(path_id)
    if baked is None:
        return None
    return Geometry(
        name=name,
        positions=np.array(baked["positions"], dtype=np.float32),
        normals=np.array(baked["normals"], dtype=np.float32),
        indices=np.array(baked["indices"], dtype=np.uint32),
        tangents=np.array(baked["tangents"], dtype=np.float32),
        uvs=[np.array(uv, dtype=np.float32) for uv in baked["uvs"]],
        uv_channels=list(baked["uv_channels"]),
    )
