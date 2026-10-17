import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger("pgr-assets")

TRANSFORM_TYPE = 4
BLEND_SHAPE_TYPE = 137
TRANSFORM_WIDTH = {1: 3, 2: 4, 3: 3, 4: 3}
POSITION, ROTATION, SCALE, EULER = 1, 2, 3, 4
DEFAULT_RATE = 30.0
FINITE_LIMIT = 1e30
BEGIN_TOLERANCE = 1e-4


@dataclass(frozen=True)
class Track:
    """
    One property of every node that animates it. Nodes ascend, values are
    (nodes, frames, width).
    """

    nodes: np.ndarray
    values: np.ndarray


@dataclass(frozen=True)
class MorphCurve:
    node: int
    name_hash: int
    values: np.ndarray


@dataclass(frozen=True)
class Animation:
    times: np.ndarray
    translation: Track
    rotation: Track
    scale: Track
    loop: bool
    morphs: list[MorphCurve] = field(default_factory=list)


@dataclass(frozen=True)
class Streamed:
    """
    Every finite key of a StreamedClip, ordered by slot then time.
    """

    slots: np.ndarray
    times: np.ndarray
    coefficients: np.ndarray


def sample_times(clip: Any, dense: Any) -> np.ndarray:
    """
    The one grid every curve in the clip is sampled onto.

    m_DenseClip.m_FrameCount runs one frame past m_StopTime and duplicates its
    last sample, so it is not the timeline even when a dense sub-clip exists.
    """
    muscle = clip.m_MuscleClip
    rate = dense.m_SampleRate or clip.m_SampleRate or DEFAULT_RATE
    start = muscle.m_StartTime
    drift = abs(dense.m_BeginTime - start)
    if drift:
        # Anything under a millisecond is float noise in the stored begin time.
        report = logger.warning if drift > BEGIN_TOLERANCE else logger.debug
        report(f"{clip.m_Name}: dense begins at {dense.m_BeginTime}, clip at {start}")
    frames = max(1, round(muscle.m_StopTime * rate) + 1)
    return np.arange(frames, dtype=np.float32) / rate + start


def parse_streamed(streamed: Any, name: str) -> Streamed:
    """
    StreamedClip.data is frames of a time, a key count, then a slot and four
    cubic coefficients per key. Only the frame headers need a walk.
    """
    ints = np.asarray(streamed.data, np.uint32).view(np.int32)
    words = ints.tolist()
    frames: list[int] = []
    counts: list[int] = []
    at, end = 0, len(words)
    while at < end:
        count = words[at + 1] if at + 1 < end else -1
        if count < 0 or at + 2 + count * 5 > end:
            logger.warning(
                f"{name}: streamed frame at word {at} runs past the data, rest dropped"
            )
            break
        frames.append(at)
        counts.append(count)
        at += 2 + count * 5

    keys = np.concatenate(
        [ints[at + 2 : at + 2 + 5 * count] for at, count in zip(frames, counts)]
        or [np.empty(0, np.int32)]
    ).reshape(-1, 5)
    times = np.repeat(ints.view(np.float32)[frames], counts)
    keep = np.isfinite(times) & (np.abs(times) < FINITE_LIMIT)
    keys, times = keys[keep], times[keep]
    # Stable, so keys sharing a slot and time stay in frame order.
    order = np.lexsort((times, keys[:, 0]))
    keys = keys[order]
    return Streamed(keys[:, 0], times[order], keys[:, 1:].view(np.float32))


def eval_streamed(keys: Streamed, count: int, times: np.ndarray) -> np.ndarray:
    """
    Slots 0 to count sampled onto times, (count, frames). A slot without keys
    reads zero, a sample before a slot's first key extrapolates that key.
    """
    out = np.zeros((count, len(times)), np.float32)
    inside = (keys.slots >= 0) & (keys.slots < count)
    slots = keys.slots[inside].astype(np.int64)
    if not len(slots):
        return out
    key_times, coefficients = keys.times[inside], keys.coefficients[inside]

    frames = len(times)
    total = np.bincount(slots, minlength=count)
    first = np.cumsum(total) - total
    # A key takes over from the first sample at or after its time, so the keys
    # in charge of a sample are the running count of takeovers in its slot.
    takeover = np.searchsorted(times, key_times, side="left")
    active = np.bincount(
        slots * (frames + 1) + takeover, minlength=count * (frames + 1)
    )
    active = active.reshape(count, frames + 1)[:, :frames].cumsum(axis=1)

    keyed = np.flatnonzero(total)
    last = total[keyed, None] - 1
    segment = first[keyed, None] + np.clip(active[keyed] - 1, 0, last)
    dx = np.maximum(times - key_times[segment], 0.0)
    c = coefficients[segment]
    out[keyed] = ((c[..., 0] * dx + c[..., 1]) * dx + c[..., 2]) * dx + c[..., 3]
    return out


def decode_clip(clip: Any, table: dict[int, int]) -> Animation:
    """
    One clip's transform curves, sampled onto a single grid, in Unity space.
    """
    data = clip.m_MuscleClip.m_Clip.data
    times = sample_times(clip, data.m_DenseClip)
    take = _make_slot_reader(
        clip.m_Name, data.m_StreamedClip, data.m_DenseClip, data.m_ConstantClip, times
    )

    starts: dict[int, dict[int, int]] = {}
    morphs: dict[tuple[int, int], MorphCurve] = {}
    slot = 0
    for entry in clip.m_ClipBindingConstant.genericBindings:
        width = _measure_width(clip, entry)
        if entry.typeID == BLEND_SHAPE_TYPE:
            node = table.get(entry.path)
            if node is not None:
                curve = _read_morph(clip, node, int(entry.attribute), take, slot)
                if curve is not None:
                    morphs[(node, curve.name_hash)] = curve
        elif entry.typeID == TRANSFORM_TYPE:
            node = table.get(entry.path)
            if node is not None:
                starts.setdefault(node, {})[entry.attribute] = slot
        slot += width

    def track(kind: str, attribute: int) -> Track:
        nodes = [node for node in sorted(starts) if attribute in starts[node]]
        firsts = [starts[node][attribute] for node in nodes]
        return _read_track(clip, kind, nodes, _read(take, firsts, 3))

    return Animation(
        times=times,
        translation=track("position", POSITION),
        rotation=_read_rotation_track(clip, starts, take),
        scale=track("scale", SCALE),
        loop=clip.m_MuscleClip.m_LoopTime,
        morphs=list(morphs.values()),
    )


def euler_to_quaternion(degrees: np.ndarray) -> np.ndarray:
    """
    Unity's Quaternion.Euler: q = qY(y) * qX(x) * qZ(z), applied Z then X then Y.

    That is three.js Euler order 'YXZ', the same rotation under the other naming.
    """
    half = np.deg2rad(np.asarray(degrees, np.float64)) * 0.5
    cos, sin = np.cos(half), np.sin(half)
    cx, cy, cz = cos[:, 0], cos[:, 1], cos[:, 2]
    sx, sy, sz = sin[:, 0], sin[:, 1], sin[:, 2]
    return np.stack(
        [
            cy * sx * cz + sy * cx * sz,
            sy * cx * cz - cy * sx * sz,
            cy * cx * sz - sy * sx * cz,
            cy * cx * cz + sy * sx * sz,
        ],
        axis=1,
    ).astype(np.float32)


def _read_rotation_track(
    clip: Any,
    starts: dict[int, dict[int, int]],
    take: Callable[[np.ndarray], np.ndarray],
) -> Track:
    """
    Local rotations, from a quaternion binding or a three-wide euler one. The
    euler replaces the rotation, it does not compose with the rest pose.

    An all-zero rotation is a default-constructed transform block with the
    quaternion's w left at zero, not a rotation. Dropping it leaves the node at
    its rest pose, which substituting identity would not.
    """
    quaternions: list[int] = []
    eulers: list[int] = []
    for node in sorted(starts):
        if ROTATION in starts[node]:
            quaternions.append(node)
            if EULER in starts[node]:
                logger.warning(
                    f"{clip.m_Name}: node {node} binds both a quaternion and an euler"
                    " rotation, the euler is dropped"
                )
        elif EULER in starts[node]:
            eulers.append(node)

    euler = _read(take, [starts[node][EULER] for node in eulers], 3)
    values = np.concatenate(
        [
            _read(take, [starts[node][ROTATION] for node in quaternions], 4),
            euler_to_quaternion(euler.reshape(-1, 3)).reshape(*euler.shape[:2], 4),
        ]
    )
    nodes = quaternions + eulers
    order = np.argsort(nodes, kind="stable")
    track = _read_track(clip, "rotation", [nodes[at] for at in order], values[order])

    zero = ~track.values.any(axis=(1, 2))
    return Track(track.nodes[~zero], _align(track.values[~zero]))


def _read_track(clip: Any, kind: str, nodes: list[int], values: np.ndarray) -> Track:
    """
    Bridge each node's non-finite runs, and drop the nodes beyond saving.
    """
    keep = np.ones(len(nodes), bool)
    for at in np.flatnonzero(~np.isfinite(values).all(axis=(1, 2))):
        repaired = _repair(clip, nodes[at], kind, values[at])
        if repaired is None:
            keep[at] = False
        else:
            values[at] = repaired
    return Track(np.array(nodes, np.int64)[keep], values[keep])


def _read(
    take: Callable[[np.ndarray], np.ndarray], firsts: list[int], width: int
) -> np.ndarray:
    """
    The width slots from each first slot on, as (tracks, frames, width).
    """
    index = np.array(firsts, np.int64).reshape(-1, 1) + np.arange(width)
    return np.ascontiguousarray(take(index).transpose(0, 2, 1))


def _read_morph(
    clip: Any,
    node: int,
    name_hash: int,
    take: Callable[[np.ndarray], np.ndarray],
    slot: int,
) -> MorphCurve | None:
    try:
        values = take(np.array([slot])).reshape(-1, 1)
        values = _repair(clip, node, "blendShape", values)
    except Exception as error:  # noqa: BLE001  costs one curve
        logger.warning(
            f"{clip.m_Name}: node {node} blendShape curve unreadable,"
            f" {type(error).__name__}: {error}"
        )
        return None
    return None if values is None else MorphCurve(node, name_hash, values[:, 0])


def _measure_width(clip: Any, entry: Any) -> int:
    if entry.typeID != TRANSFORM_TYPE:
        return 1
    if entry.attribute not in TRANSFORM_WIDTH:
        raise ValueError(f"{clip.m_Name}: transform attribute {entry.attribute}")
    return TRANSFORM_WIDTH[entry.attribute]


def _make_slot_reader(
    name: str, streamed: Any, dense: Any, constant: Any, times: np.ndarray
) -> Callable[[np.ndarray], np.ndarray]:
    """
    One global slot numbering across the three sub-clips, streamed first. The
    reader takes an array of slots and returns their curves on a trailing axis.
    """
    count = streamed.curveCount
    varying = [
        eval_streamed(parse_streamed(streamed, name), count, times)
        if count
        else np.empty((0, len(times)), np.float32)
    ]
    if dense.m_CurveCount:
        if dense.m_FrameCount < len(times):
            raise ValueError(
                f"dense clip has {dense.m_FrameCount} frames, needs {len(times)}"
            )
        samples = np.asarray(dense.m_SampleArray, np.float32).reshape(
            dense.m_FrameCount, dense.m_CurveCount
        )
        varying.append(samples[: len(times)].T)
    curves = np.concatenate(varying)
    constants = np.asarray(constant.data, np.float32)

    def take(slots: np.ndarray) -> np.ndarray:
        out = np.empty((*slots.shape, len(times)), np.float32)
        held = slots >= len(curves)
        out[~held] = curves[slots[~held]]
        out[held] = constants[slots[held] - len(curves), None]
        return out

    return take


def _repair(clip: Any, node: int, kind: str, values: np.ndarray) -> np.ndarray | None:
    """
    Bridge the non-finite runs a clip's own keyframes leave behind.
    """
    if np.isfinite(values).all():
        return values

    good = np.isfinite(values).all(axis=1)
    if not good.any():
        logger.warning(f"{clip.m_Name}: node {node} {kind} is all non-finite, dropped")
        return None

    before, after, fraction = _bracket(good)
    if kind == "rotation":
        filled = _slerp(values[before], values[after], fraction)
        how = "slerps"
    else:
        filled = values[before] * (1.0 - fraction) + values[after] * fraction
        how = "lerps"

    logger.warning(
        f"{clip.m_Name}: node {node} {kind} {how}"
        f" {int((~good).sum())} of {len(good)} non-finite frames"
    )
    repaired = values.copy()
    repaired[~good] = filled[~good]
    return repaired


def _bracket(good: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Per frame, the nearest finite frame on each side and the fraction between
    them. Runs that reach an end of the clip bracket against that end alone.
    """
    count = len(good)
    frames = np.arange(count)
    finite = np.flatnonzero(good)

    before = np.maximum.accumulate(np.where(good, frames, -1))
    before[before < 0] = finite[0]
    after = np.minimum.accumulate(np.where(good, frames, count)[::-1])[::-1]
    after[after >= count] = finite[-1]

    span = (after - before).astype(np.float32)
    fraction = np.where(
        span > 0, (frames - before) / np.where(span > 0, span, 1.0), 0.0
    )
    return before, after, fraction[:, None].astype(np.float32)


def _slerp(a: np.ndarray, b: np.ndarray, fraction: np.ndarray) -> np.ndarray:
    dots = np.sum(a * b, axis=1, keepdims=True)
    b = np.where(dots < 0.0, -b, b)
    theta = np.arccos(np.clip(np.abs(dots), -1.0, 1.0))
    sin = np.sin(theta)
    straight = sin < 1e-6
    weight_a = np.where(
        straight,
        1.0 - fraction,
        np.sin((1.0 - fraction) * theta) / np.where(straight, 1.0, sin),
    )
    weight_b = np.where(
        straight, fraction, np.sin(fraction * theta) / np.where(straight, 1.0, sin)
    )
    return (a * weight_a + b * weight_b).astype(np.float32)


def _align(values: np.ndarray) -> np.ndarray:
    """
    Flip each key into the hemisphere of the key before it, then renormalize.
    """
    dots = np.sum(values[:, 1:] * values[:, :-1], axis=2)
    flips = np.cumprod(np.where(dots < 0, -1.0, 1.0), axis=1)
    signs = np.concatenate((np.ones((len(values), 1)), flips), axis=1)
    aligned = values * signs[..., None]
    norms = np.linalg.norm(aligned, axis=2, keepdims=True)
    return (aligned / np.where(norms == 0.0, 1.0, norms)).astype(np.float32)
