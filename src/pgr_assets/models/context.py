"""
A context is one of the situations the game shows a model in, with the controller
it plays, the nodes it hides and the mounts it hangs weapons on.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import Enum

import numpy as np

from pgr_assets.models.animation import euler_to_quaternion
from pgr_assets.models.coords import conjugate_quat
from pgr_assets.models.prefab import Node, ObjectTag, find_node

MAX_SLOTS = 9

FIGHT_CONTEXT = "fight"
MENU_CONTEXT = "menu"
SHOW_CONTEXT = "show"


class RestPolicy(Enum):
    """
    Where a context comes to rest once its entry state has played.
    """

    # The controller's idle state.
    IDLE_STATE = "idle"
    # The entry state itself, the controller starts resting.
    ENTRY = "entry"
    # Follow the transitions the UI fires from the start, and rest where they end.
    UI_CHAIN_END = "ui_chain_end"


@dataclass(frozen=True)
class Mount:
    slot: int
    name: str
    node: int
    skill_node: int | None = None


@dataclass(frozen=True)
class Context:
    name: str
    base: str | None = None
    levels: tuple[str, ...] = ()
    # Where the game starts: a layer named by the npc layer table, else layer 0, in
    # a state named by the weapon table, else that layer's default.
    start_layer: str | None = None
    start_state: str | None = None
    # The UI's own clip, played without a controller.
    clip: str | None = None
    hidden: tuple[int, ...] = ()
    mounts: tuple[Mount, ...] = ()
    rest: RestPolicy = RestPolicy.IDLE_STATE
    # glTF xyzw the model root turns to.
    rotation: tuple[float, ...] | None = None


def resolve_name(
    name: str, nodes: Sequence[Node], tags: Sequence[ObjectTag]
) -> list[int]:
    """
    What the engine finds for a name: the last tag row of that name even when it's
    empty, else the shallowest node of that name.
    """
    rows = [tag for tag in tags if tag.name == name]
    if rows:
        return rows[-1].nodes
    node = find_node(nodes, name)
    return [] if node is None else [node]


def resolve_joint(
    name: str, nodes: Sequence[Node], tags: Sequence[ObjectTag]
) -> int | None:
    found = resolve_name(name, nodes, tags)
    return found[0] if found else None


def resolve_mounts(
    prefix: str, nodes: Sequence[Node], tags: Sequence[ObjectTag]
) -> tuple[Mount, ...]:
    found = []
    for slot in range(1, MAX_SLOTS + 1):
        name = f"{prefix}{slot}"
        node = resolve_joint(name, nodes, tags)
        if node is not None:
            skill = resolve_joint(f"{prefix}Ex{slot}", nodes, tags)
            found.append(Mount(slot, name, node, skill))
    return tuple(found)


def resolve_hidden(
    names: Collection[str], nodes: Sequence[Node], tags: Sequence[ObjectTag]
) -> tuple[int, ...]:
    """
    Skins share one npc row, so a sibling skin's names arrive here too and resolve
    to nothing.
    """
    hidden = {node for name in names for node in resolve_name(name, nodes, tags)}
    return tuple(sorted(hidden))


def keep_present(paths: Sequence[str | None], present: Collection[str]) -> list[str]:
    return [path for path in paths if path is not None and path in present]


def convert_rotation(degrees: Sequence[float]) -> tuple[float, ...]:
    """
    Unity euler degrees as a glTF xyzw quaternion.
    """
    quaternion = conjugate_quat(euler_to_quaternion(np.array([degrees])))[0]
    return tuple(float(value) for value in quaternion)
