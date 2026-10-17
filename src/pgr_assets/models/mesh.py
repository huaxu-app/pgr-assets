import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np
from numpy.typing import DTypeLike
from UnityPy.enums.VertexFormat import VertexFormat
from UnityPy.helpers.MeshHelper import MeshHandler

from pgr_assets.models import coords
from pgr_assets.models.rig import Skin
from pgr_assets.models.unity import read_uv_channel

logger = logging.getLogger("pgr-assets")

INFLUENCES = 4
UV_CHANNELS = 8
COLOR_CHANNEL = 3

class Uv3Layout(Enum):
    """
    What the mesh's fourth UV channel holds, which only the shader knows.
    """

    TEXCOORD = "texcoord"
    SMOOTH_NORMAL = "smooth_normal"


COLOR_SCALE = {
    VertexFormat.kVertexFormatFloat: 1.0,
    VertexFormat.kVertexFormatFloat16: 1.0,
    VertexFormat.kVertexFormatUNorm8: 255.0,
    VertexFormat.kVertexFormatSNorm8: 127.0,
    VertexFormat.kVertexFormatUNorm16: 65535.0,
    VertexFormat.kVertexFormatSNorm16: 32767.0,
}


@dataclass(frozen=True)
class MorphTarget:
    name: str
    name_hash: int
    full_weight: float
    rest_influence: float
    indices: np.ndarray
    positions: np.ndarray
    normals: np.ndarray | None
    tangents: np.ndarray | None


@dataclass(frozen=True)
class MorphChannel:
    index: int
    full_weight: float
    rest_influence: float


@dataclass(frozen=True)
class Geometry:
    name: str
    positions: np.ndarray
    normals: np.ndarray | None
    indices: np.ndarray
    joints: np.ndarray | None = None
    weights: np.ndarray | None = None
    rigid: bool = False
    uvs: list[np.ndarray] = field(default_factory=list)
    uv_channels: list[int] = field(default_factory=list)
    tangents: np.ndarray | None = None
    colors: np.ndarray | None = None
    smooth_normal: np.ndarray | None = None
    zones: np.ndarray | None = None
    morphs: list[MorphTarget] = field(default_factory=list)

    def find_uv_slot(self, channel: int) -> int | None:
        if channel not in self.uv_channels:
            return None
        return self.uv_channels.index(channel)

    def resolve_tex_coord(self, channel: int) -> int:
        """
        The TEXCOORD a Unity UV channel landed in. One past the last names nothing,
        so a reader samples a zero UV like Unity does.
        """
        slot = self.find_uv_slot(channel)
        return len(self.uvs) if slot is None else slot


def read_geometry(
    mesh: Any,
    where: str,
    uv3: Uv3Layout,
    rest_weights: Sequence[float],
    skin: Skin | None,
) -> Geometry:
    """
    Everything the mesh asset holds, in glTF space, with influences bound to the
    skin that will drive them.
    """
    handler = MeshHandler(mesh)
    handler.process()

    positions = coords.flip_z(np.asarray(handler.m_Vertices, np.float32)[:, :3])
    count = len(positions)

    normals = None
    if handler.m_Normals is not None and len(handler.m_Normals) == count:
        normals = coords.flip_z(np.asarray(handler.m_Normals, np.float32)[:, :3])

    # Submeshes partition one shared index buffer and the indices are absolute,
    # so they concatenate.
    triangles = [
        np.asarray(s, np.uint32).reshape(-1, 3) for s in handler.get_triangles()
    ]
    indices = coords.reverse_winding(np.concatenate(triangles))

    uvs, uv_channels, packed_normal = _read_uvs(handler, count, where, uv3)
    joints, weights, rigid = _read_influences(handler, count, where)
    if skin is not None and joints is not None and weights is not None:
        joints, weights = bind_influences(joints, weights, skin, where)
    tangents = _read_channel(handler.m_Tangents, count, 4, where, "tangents")
    if tangents is not None:
        tangents = coords.flip_tangent(tangents)
    return Geometry(
        name=mesh.m_Name,
        positions=positions,
        normals=normals,
        indices=indices,
        joints=joints,
        weights=weights,
        rigid=rigid,
        uvs=uvs,
        uv_channels=uv_channels,
        tangents=tangents,
        colors=_read_colors(mesh, handler, count, where),
        smooth_normal=packed_normal,
        zones=_read_zones(handler, count),
        morphs=read_morphs(mesh, rest_weights, where, count),
    )


def _read_colors(mesh: Any, handler: Any, count: int, where: str) -> np.ndarray | None:
    colors = _read_channel(handler.m_Colors, count, 4, where, "colors")
    # Compressed colors are already normalized.
    if colors is None or mesh.m_CompressedMesh.m_FloatColors.m_NumItems:
        return colors
    channel = mesh.m_VertexData.m_Channels[COLOR_CHANNEL]
    return _normalize_colors(colors, channel.format, where)


def _normalize_colors(colors: np.ndarray, format: int, where: str) -> np.ndarray:
    # MeshHandler leaves normalized integer formats as raw integers.
    scale = COLOR_SCALE.get(VertexFormat(format))
    if scale is None:
        logger.warning(
            f"{where}: colors are {VertexFormat(format).name}, left unnormalized"
        )
        return colors
    if scale == 1.0:
        return colors
    return np.maximum(colors / np.float32(scale), -1)


SMOOTH_NORMAL_CHANNEL = 3
ZONE_CHANNEL = 1


def _read_uvs(
    handler: Any, count: int, where: str, uv3: Uv3Layout
) -> tuple[list[np.ndarray], list[int], np.ndarray | None]:
    uvs, channels = [], []
    packed = None
    for channel in range(UV_CHANNELS):
        packed_here = uv3 is Uv3Layout.SMOOTH_NORMAL and channel == SMOOTH_NORMAL_CHANNEL
        width = 3 if packed_here else 2
        values = _read_channel(
            read_uv_channel(handler, channel), count, width, where, f"uv{channel}"
        )
        if values is None:
            continue
        if packed_here:
            packed = coords.flip_v(values)
            continue
        uvs.append(coords.flip_v(values))
        channels.append(channel)
    return uvs, channels, packed


def _read_zones(handler: Any, count: int) -> np.ndarray | None:
    values = read_uv_channel(handler, ZONE_CHANNEL)
    if values is None or not len(values) or len(values) != count:
        return None
    array = np.asarray(values, np.float32).reshape(count, -1)
    if array.shape[1] < 3:
        return None
    # The zoned programs read zw as ids, not coordinates, so no V flip. GL fills
    # a missing w with 1.
    zones = np.ones((count, 2), np.float32)
    width = min(array.shape[1], 4) - 2
    zones[:, :width] = array[:, 2 : 2 + width]
    return zones


def _read_channel(
    values: Any, count: int, width: int, where: str, what: str
) -> np.ndarray | None:
    if values is None or not len(values):
        return None
    if len(values) != count:
        logger.warning(f"{where}: {len(values)} {what} for {count} vertices, dropped")
        return None

    array = np.asarray(values, np.float32).reshape(count, -1)
    if array.shape[1] < width:
        logger.warning(
            f"{where}: {what} are {array.shape[1]} wide, need {width}, dropped"
        )
        return None
    return np.ascontiguousarray(array[:, :width])


def read_morphs(
    mesh: Any, rest: Sequence[float], where: str, vertex_count: int
) -> list[MorphTarget]:
    """
    One glTF morph target per blendshape channel.

    Everything downstream reads these values as they stand: the rest influence
    is already divided by the channel's own full weight. Dividing again at a use
    site is how the glb and the clip files come to disagree.
    """
    try:
        return _read_morphs(mesh, rest, where, vertex_count)
    except Exception as error:  # noqa: BLE001  a face shape must not cost a mesh
        logger.warning(
            f"{where}: blendshapes unreadable, {type(error).__name__}: {error}"
        )
        return []


def _read_morphs(
    mesh: Any, weights: Sequence[float], where: str, vertex_count: int
) -> list[MorphTarget]:
    shapes = mesh.m_Shapes
    if shapes is None:
        return []
    channels = list(shapes.channels or ())
    if not channels:
        return []

    frames = list(shapes.shapes or ())
    vertices = list(shapes.vertices or ())
    full_weights = [float(w) for w in (shapes.fullWeights or ())]
    rest = [float(w) for w in weights]
    if len(rest) > len(channels):
        logger.warning(
            f"{where}: {len(rest)} blendshape weights for {len(channels)} channels"
        )

    authored = any(f.hasNormals for f in frames)
    tangented = any(f.hasTangents for f in frames)
    arrays = _stack_shape_arrays(vertices, authored, tangented)

    targets: list[MorphTarget] = []
    dropped_indices = 0
    for index, channel in enumerate(channels):
        frame = _pick_strongest_frame(channel, full_weights, where)
        if frame is None:
            continue
        if frame >= len(frames):
            logger.warning(
                f"{where}/{channel.name}: frame {frame} out of range, channel dropped"
            )
            continue

        if frame >= len(full_weights) or full_weights[frame] <= 0.0:
            logger.warning(
                f"{where}/{channel.name}: no usable full weight, channel dropped"
            )
            continue
        weight = full_weights[frame]

        indices, positions, normals, tangents, dropped = _read_deltas(
            arrays, frames[frame], vertex_count
        )
        dropped_indices += dropped
        targets.append(
            MorphTarget(
                name=channel.name,
                name_hash=int(channel.nameHash),
                full_weight=weight,
                rest_influence=(rest[index] / weight) if index < len(rest) else 0.0,
                indices=indices,
                positions=positions,
                normals=normals,
                tangents=tangents,
            )
        )
    if dropped_indices:
        logger.warning(
            f"{where}: {dropped_indices} morph delta indices past"
            f" {vertex_count} vertices, dropped"
        )
    return targets


def _pick_strongest_frame(channel: Any, full_weights: list[float], where: str) -> int | None:
    first, count = int(channel.frameIndex), int(channel.frameCount)
    if count == 0:
        logger.warning(f"{where}/{channel.name}: 0 frames, channel dropped")
        return None
    if count == 1:
        return first
    reachable = [f for f in range(first, first + count) if f < len(full_weights)]
    if not reachable:
        return first
    # glTF has no in-between concept. The strongest frame is exact at influence
    # 1.0, where dropping the channel would lose the shape at every weight.
    logger.warning(f"{where}/{channel.name}: {count} frames, keeping the strongest")
    return max(reachable, key=lambda f: full_weights[f])


def _stack_shape_arrays(
    vertices: list[Any], normals: bool, tangents: bool
) -> dict[str, np.ndarray]:
    """
    Every blend shape vertex in one pass, each frame slices its span out after.
    """
    arrays: dict[str, np.ndarray] = {
        "index": np.asarray([int(v.index) for v in vertices], np.uint32)
    }
    for attribute, want in (("vertex", True), ("normal", normals), ("tangent", tangents)):
        if not want:
            continue
        points = [getattr(v, attribute) for v in vertices]
        arrays[attribute] = np.asarray(
            [(p.x, p.y, p.z) for p in points], np.float32
        ).reshape(-1, 3)
    return arrays


def _read_deltas(
    arrays: dict[str, np.ndarray], frame: Any, count: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None, np.ndarray | None, int]:
    first, span_count = int(frame.firstVertex), int(frame.vertexCount)
    span = slice(first, first + span_count)
    raw = arrays["index"][span]
    order = np.argsort(raw, kind="stable")
    keep = order[np.unique(raw[order], return_index=True)[1]]

    in_range = raw[keep] < count
    dropped = int((~in_range).sum())
    keep = keep[in_range]

    def stack(attribute: str) -> np.ndarray | None:
        array = arrays.get(attribute)
        return None if array is None else coords.flip_z(array[span][keep])

    positions = coords.flip_z(arrays["vertex"][span][keep])
    return raw[keep], positions, stack("normal"), stack("tangent"), dropped


def bind_influences(
    joints: np.ndarray, weights: np.ndarray, skin: Skin, where: str
) -> tuple[np.ndarray, np.ndarray]:
    """
    The influences with every one the skin cannot honor neutralized.

    An influence is unusable when its slot names a bone that did not resolve, or
    when it points past the end of the joint list. Both would otherwise place
    vertices under an unrelated matrix, and the second makes the glTF invalid.
    """
    unusable = joints >= len(skin.joints)
    if unusable.any():
        logger.warning(
            f"{where}: {int(unusable.sum())} influences index past"
            f" {len(skin.joints)} joints"
        )
    if skin.unresolved:
        unusable |= np.isin(joints, list(skin.unresolved))

    if not unusable.any():
        return joints, weights

    joints, weights = joints.copy(), weights.copy()
    joints[unusable] = 0
    weights[unusable] = 0.0
    _renormalize(joints, weights)
    return joints, weights


def _renormalize(joints: np.ndarray, weights: np.ndarray) -> None:
    total = weights.sum(axis=1)
    scaled = total > 0
    weights[scaled] /= total[scaled, None]

    # Every influence on this vertex was unusable, so bind it rigidly to joint 0
    # rather than leaving it weightless.
    weights[~scaled, 0] = 1.0
    joints[~scaled] = 0


def _read_influences(
    handler: Any, vertices: int, where: str
) -> tuple[np.ndarray | None, np.ndarray | None, bool]:
    if handler.m_BoneIndices is None:
        return None, None, False

    joints = _fit_influences(handler.m_BoneIndices, vertices, np.uint16, where, "indices")
    if joints is None:
        return None, None, False

    if handler.m_BoneWeights is None:
        # Rigid binding: one bone per vertex and no weight stream at all. The padded
        # index columns are inert because their weights are zero.
        weights = np.zeros((vertices, INFLUENCES), np.float32)
        weights[:, 0] = 1.0
        return joints, weights, True

    weights = _fit_influences(handler.m_BoneWeights, vertices, np.float32, where, "weights")
    if weights is None:
        return None, None, False
    return joints, weights, False


def _fit_influences(
    values: Sequence[Any],
    vertices: int,
    dtype: DTypeLike,
    where: str,
    what: str,
) -> np.ndarray | None:
    if len(values) != vertices:
        logger.warning(
            f"{where}: {len(values)} blend {what} for {vertices} vertices, unskinned"
        )
        return None

    fitted = np.asarray(values, dtype).reshape(vertices, -1)
    if fitted.shape[1] > INFLUENCES:
        logger.warning(
            f"{where}: blend {what} are {fitted.shape[1]} wide,"
            f" keeping {INFLUENCES} and dropping the rest"
        )
    if fitted.shape[1] >= INFLUENCES:
        return np.ascontiguousarray(fitted[:, :INFLUENCES])

    padding = np.zeros((vertices, INFLUENCES - fitted.shape[1]), dtype)
    return np.concatenate([fitted, padding], axis=1)
