"""
The animator controller walk: layers, states, blend trees and the UI chain. Pure
Unity structure, nothing here decodes a clip or touches disk.
"""

import logging
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pgr_assets.models.format import Blending

logger = logging.getLogger("pgr-assets")

SENTINEL_CLIP = 0xFFFFFFFF
SIMPLE_1D = 0

FLOAT_PARAMETER = 1
INT_PARAMETER = 3
# Unity's AnimatorConditionMode, a parameter value against the threshold.
CONDITIONS: dict[int, Callable[[float, float], bool]] = {
    1: lambda value, _: value != 0.0,
    2: lambda value, _: value == 0.0,
    3: lambda value, threshold: value > threshold,
    4: lambda value, threshold: value < threshold,
    6: lambda value, threshold: value == threshold,
    7: lambda value, threshold: value != threshold,
}
# What the UI sets once a weapon is on screen. Everything else stays at its default.
UI_FIRED = {"UiActionBegin": 1.0}


@dataclass(frozen=True)
class Layer:
    source: str
    name: str
    blending: Blending
    weight: float
    masked: bool
    mask: tuple[int, ...]
    default_state: str | None
    # State to the state the UI moves it on to, by its parameters or exit time alone.
    ui_next: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class StateTiming:
    speed: float
    cycle_offset: float
    mirror: bool


@dataclass(frozen=True)
class AnimatorState:
    name: str
    # Every motion the state's blend tree holds, in tree order, repeats kept.
    clips: tuple[int, ...]
    # The one that dominates at the parameters' default values.
    dominant: int
    timing: StateTiming
    # m_FullPathID, which is what a behavior's StateKey names.
    path_id: int


def read_controller(
    controller: Any, source: str, table: dict[int, int]
) -> list[tuple[Layer, list[AnimatorState]]]:
    names = dict(controller.m_TOS)
    clip_count = len(controller.m_AnimationClips)
    constant = controller.m_Controller
    machines = list(constant.m_StateMachineArray)
    defaults = _read_parameter_defaults(constant)
    fired = {
        key: value
        for key, value in ((k, UI_FIRED.get(names.get(k, ""))) for k in defaults)
        if value is not None
    }
    ui_values = defaults | fired

    groups: list[tuple[Layer, list[AnimatorState]]] = []
    for index, raw in enumerate(constant.m_LayerArray):
        entry = raw.data
        if (
            entry.m_StateMachineMotionSetIndex
            or entry.m_StateMachineSynchronizedLayerIndex
        ):
            raise ValueError(f"layer {index} indexes into a motion set")

        mask = entry.m_SkeletonMask.data.m_Data
        name = names.get(entry.m_Binding)
        if name is None:
            name = f"layer{index}"
            logger.warning(f"{source}: layer {index} is unnamed, shipped as {name}")
        machine = None
        if 0 <= entry.m_StateMachineIndex < len(machines):
            machine = machines[entry.m_StateMachineIndex].data
        else:
            logger.warning(
                f"layer {index}: state machine {entry.m_StateMachineIndex}"
                f" of {len(machines)}"
            )
        layer = Layer(
            source=source,
            name=name,
            blending="additive" if entry.m_LayerBlendingMode else "override",
            weight=entry.m_DefaultWeight,
            masked=bool(mask),
            mask=_resolve_mask_nodes(mask, table),
            default_state=None if machine is None else _read_entry_state(machine, names),
            ui_next=() if machine is None else _read_ui_next(machine, names, ui_values),
        )
        states: list[AnimatorState] = []
        if machine is not None:
            states = _read_states(machine, names, clip_count, defaults)
        groups.append((layer, states))

    return groups


def _resolve_mask_nodes(mask: Any, table: dict[int, int]) -> tuple[int, ...]:
    """
    Nodes the mask admits. Weights are 0 or 1 roster-wide, and an admitted path
    the prefab lacks is inert.
    """
    nodes = {table.get(e.m_PathHash) for e in mask if e.m_Weight > 0}
    return tuple(sorted(n for n in nodes if n is not None))


def _read_entry_state(machine: Any, names: dict[int, str]) -> str | None:
    states: list[Any] = machine.m_StateConstantArray
    index = machine.m_DefaultState
    if not 0 <= index < len(states):
        return None
    return names.get(states[index].data.m_NameID)


def _read_parameter_defaults(constant: Any) -> dict[int, float]:
    """
    Parameter defaults by name hash, which is what blend nodes and conditions key on.
    Bools and triggers come out as 0 or 1.
    """
    stored = constant.m_DefaultValues.data
    arrays: dict[int, list[float]] = {
        FLOAT_PARAMETER: [float(v) for v in stored.m_FloatValues],
        INT_PARAMETER: [float(v) for v in stored.m_IntValues],
    }
    bools = [float(v) for v in stored.m_BoolValues]
    found: dict[int, float] = {}
    for value in constant.m_Values.data.m_ValueArray:
        array = arrays.get(value.m_Type, bools)
        if 0 <= value.m_Index < len(array):
            found[value.m_ID] = array[value.m_Index]
    return found


def _condition_holds(condition: Any, values: dict[int, float]) -> bool:
    test = CONDITIONS.get(condition.m_ConditionMode)
    value = values.get(condition.m_EventID, 0.0)
    return test is not None and test(value, condition.m_EventThreshold)


def _read_ui_next(
    machine: Any, names: dict[int, str], values: dict[int, float]
) -> tuple[tuple[str, str], ...]:
    states = [raw.data for raw in machine.m_StateConstantArray]
    found: list[tuple[str, str]] = []
    for state in states:
        source = names.get(state.m_NameID)
        for raw in state.m_TransitionConstantArray:
            transition = raw.data
            target = transition.m_DestinationState
            if not 0 <= target < len(states):
                continue
            if all(_condition_holds(c.data, values) for c in transition.m_ConditionConstantArray):
                destination = names.get(states[target].m_NameID)
                if source is not None and destination is not None:
                    found.append((source, destination))
                break
    return tuple(found)


def _read_states(
    machine: Any, names: dict[int, str], clip_count: int, defaults: dict[int, float]
) -> list[AnimatorState]:
    states: list[AnimatorState] = []
    for raw in machine.m_StateConstantArray:
        entry = raw.data
        name = names.get(entry.m_NameID)
        if name is None:
            name = f"state{entry.m_NameID}"
            logger.warning(f"state {entry.m_NameID} is unnamed, shipped as {name}")
        clips = _read_clip_indices(entry, name, clip_count)
        if not clips:
            continue
        timing = StateTiming(
            speed=entry.m_Speed,
            cycle_offset=entry.m_CycleOffset,
            mirror=entry.m_Mirror,
        )
        dominant = _pick_dominant(entry, name, defaults)
        if dominant not in clips:
            dominant = clips[0]
        states.append(
            AnimatorState(name, tuple(clips), dominant, timing, entry.m_FullPathID)
        )
    return states


def _pick_dominant(state: Any, name: str, defaults: dict[int, float]) -> int | None:
    """
    The clip carrying the most weight with every parameter at its default. Every
    tree in the roster is Simple1D, and the defaults are 1.0, so Run plays 95% of
    its middle child and Dante's Attack163 is a 51/49 mix that reads as one.
    """
    trees: list[Any] = state.m_BlendTreeConstantArray
    if not trees:
        return None
    nodes = [node.data for node in trees[0].data.m_NodeArray]
    if len(nodes) < 2:
        return nodes[0].m_ClipID if nodes else None
    root = nodes[0]
    children = list(root.m_ChildIndices)
    if root.m_BlendType != SIMPLE_1D:
        logger.warning(f"{name}: blend type {root.m_BlendType}, first child plays")
        return nodes[children[0]].m_ClipID
    thresholds: list[float] = list(root.m_Blend1dData.data.m_ChildThresholdArray)
    value = defaults.get(root.m_BlendEventID, 0.0)
    return nodes[children[_find_nearest(thresholds, value)]].m_ClipID


def _find_nearest(thresholds: list[float], value: float) -> int:
    """
    Unity's 1D blend splits weight between the two thresholds around the value.
    """
    if value <= thresholds[0]:
        return 0
    for index in range(len(thresholds) - 1):
        low, high = thresholds[index], thresholds[index + 1]
        if value <= high:
            return index + 1 if (value - low) / (high - low) > 0.5 else index
    return len(thresholds) - 1


def _read_clip_indices(state: Any, name: str, clip_count: int) -> list[int]:
    indices: list[int] = []
    for raw in state.m_BlendTreeConstantArray:
        for node in raw.data.m_NodeArray:
            index = node.data.m_ClipID
            if 0 <= index < clip_count:
                indices.append(index)
            elif index != SENTINEL_CLIP:
                logger.warning(f"{name}: clip index {index} of {clip_count}")
    return indices


def hash_paths(paths: list[str]) -> dict[int, int]:
    """
    CRC32 of each root-relative transform path to its node index.
    """
    table: dict[int, int] = {}
    for index, path in enumerate(paths):
        key = zlib.crc32(path.encode()) & 0xFFFFFFFF
        if key in table:
            logger.warning(
                f"duplicate transform path {path!r}, node {index} unbindable"
            )
            continue
        table[key] = index
    return table
