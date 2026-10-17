import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from pgr_assets.models import coords
from pgr_assets.models.unity import read_matrix4, read_pointer, resolve_asset_key

logger = logging.getLogger("pgr-assets")


@dataclass(frozen=True)
class Skin:
    joints: list[int]
    inverse_bind: np.ndarray
    root_bone: int | None = None
    unresolved: frozenset[int] = field(default_factory=frozenset)


def read_skin(
    node_of: dict[str, int], renderer: Any, mesh: Any, where: str
) -> Skin | None:
    bones = list(renderer.m_Bones or ())
    if not bones:
        return None

    joints: list[int] = []
    unresolved: set[int] = set()
    for slot, bone in enumerate(bones):
        transform = read_pointer(bone, where, f"bone {slot}")
        resolved = None if transform is None else node_of.get(resolve_asset_key(transform))

        # A slot that cannot be honored keeps its place, because blend indices
        # address positions in this list. It is neutralized instead: node 0, an
        # identity bind pose, and every weight pointing at it zeroed.
        if resolved is None:
            unresolved.add(slot)
            resolved = 0
        joints.append(resolved)

    if unresolved:
        logger.warning(
            f"{where}: {len(unresolved)} of {len(bones)} bones did not resolve"
        )

    return Skin(
        joints=joints,
        inverse_bind=_read_bind_poses(mesh, len(joints), unresolved, where),
        root_bone=_read_root_bone(node_of, renderer, where),
        unresolved=frozenset(unresolved),
    )


def _read_bind_poses(
    mesh: Any, count: int, unresolved: set[int], where: str
) -> np.ndarray:
    poses = list(mesh.m_BindPose)
    if len(poses) < count:
        logger.warning(
            f"{where}: {len(poses)} bind poses for {count} bones,"
            " the rest bind at identity"
        )
    elif len(poses) > count:
        logger.debug(f"{where}: {len(poses)} bind poses for {count} bones")

    matrices = np.tile(np.eye(4), (count, 1, 1))
    for i, pose in enumerate(poses[:count]):
        if i in unresolved:
            continue
        matrices[i] = read_matrix4(pose)
    return coords.conjugate_matrix(matrices)


def _read_root_bone(node_of: dict[str, int], renderer: Any, where: str) -> int | None:
    transform = read_pointer(renderer.m_RootBone, where, "root bone")
    if transform is None:
        return None

    resolved = node_of.get(resolve_asset_key(transform))
    if resolved is None:
        logger.warning(f"{where}: root bone is outside the walked hierarchy")
    return resolved
