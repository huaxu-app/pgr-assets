import logging
import math
from concurrent.futures import Future, wait
from dataclasses import dataclass
from typing import cast

import numpy as np
import orjson

from pgr_assets.models import coords
from pgr_assets.models.animation import Animation
from pgr_assets.models.clips import ClipFile
from pgr_assets.models.events import Event
from pgr_assets.models.files import Publisher
from pgr_assets.models.format import (
    ANIM_DIR,
    CLIP_VERSION,
    ClipDoc,
    ConstantRow,
    DroppedRow,
    PackedRotationRow,
    PackedValueRow,
)
from pgr_assets.models.mesh import MorphChannel
from pgr_assets.models.prefab import Node, measure_depth

logger = logging.getLogger("pgr-assets")

CONSTANT_TOLERANCE = 1e-5
TIME_DIGITS = 5
VALUE_DIGITS = 6
QUATERNION_DIGITS = 5
MORPH_DIGITS = 5
ROTATION_BITS = 16
PACKED_DIGITS = 5
ROTATION_SCALE = (2 ** (ROTATION_BITS - 1) - 1) / math.sqrt(0.5)
KEPT = np.array([[c for c in range(4) if c != dropped] for dropped in range(4)])
DIGITS = {"quaternion": QUATERNION_DIGITS, "weights": MORPH_DIGITS}

Row = ConstantRow | PackedRotationRow | PackedValueRow


def round_values(values: np.ndarray, digits: int) -> list[float]:
    # float64 first. Rounding a float32 in place yields a longer shortest repr
    # and 2.09x more bytes for identical numbers.
    return np.asarray(values, np.float64).round(digits).ravel().tolist()


def _delta_encode(steps: np.ndarray) -> list[list[int]]:
    """
    Delta-encode (tracks, keys, components) along keys, then flatten each track
    by component.
    """
    deltas = np.diff(steps.astype(np.int64), axis=1, prepend=0)
    return deltas.transpose(0, 2, 1).reshape(len(steps), -1).tolist()


def pack_rotations(
    values: np.ndarray,
) -> tuple[list[list[int]], list[list[DroppedRow]]]:
    """
    Drop each key's largest quaternion component, rebuilt from unit length.
    Negate keys where that component is negative. The rest fit ±sqrt(1/2).
    """
    dropped = np.abs(values).argmax(axis=2)
    largest = np.take_along_axis(values, dropped[..., None], axis=2)
    values = values * np.where(largest < 0, -1.0, 1.0)
    kept = np.take_along_axis(values, KEPT[dropped], axis=2)
    runs: list[list[DroppedRow]] = [[] for _ in values]
    starts = np.diff(dropped, axis=1, prepend=-1) != 0
    tracks, ats = np.nonzero(starts)
    for track, at, component in zip(
        tracks.tolist(), ats.tolist(), dropped[starts].tolist()
    ):
        runs[track].append({"at": at, "component": component})
    return _delta_encode(np.round(kept * ROTATION_SCALE)), runs


def pack_values(values: np.ndarray) -> list[list[int]]:
    return _delta_encode(np.round(values * 10**PACKED_DIGITS))


def _pack_rows(
    nodes: list[int],
    prop: str,
    values: np.ndarray,
    off: np.ndarray,
    targets: list[int] | None = None,
) -> list[Row]:
    """
    One row per track, values (tracks, frames, width) in float64. A still track
    within CONSTANT_TOLERANCE of rest (off) is dropped, any other still track
    ships its first key, the rest are packed against the clip's shared times.
    """
    still = _find_still(values)
    kept = ~(still & (off < CONSTANT_TOLERANCE))
    nodes = [node for node, keep in zip(nodes, kept) if keep]
    if targets is not None:
        targets = [target for target, keep in zip(targets, kept) if keep]
    values, still = values[kept], still[kept]
    held = values[:, 0].round(DIGITS.get(prop, VALUE_DIGITS)).tolist()
    moving = ~still
    deltas: list[list[int]] = []
    runs: list[list[DroppedRow]] = []
    if moving.any():
        if prop == "quaternion":
            deltas, runs = pack_rotations(values[moving])
        else:
            deltas = pack_values(values[moving])

    rows: list[Row] = []
    packed = 0
    for at, node in enumerate(nodes):
        row: dict[str, object] = {"node": node, "property": prop}
        if still[at]:
            row["value"] = held[at]
        else:
            row["deltas"] = deltas[packed]
            if prop == "quaternion":
                row["dropped"] = runs[packed]
            packed += 1
        if targets is not None:
            row["target"] = targets[at]
        # Shape pinned by the still/moving split above, pyright can't see it.
        rows.append(cast(Row, row))
    return rows


def _find_still(values: np.ndarray) -> np.ndarray:
    """
    Tracks whose every component stays within CONSTANT_TOLERANCE, from
    (tracks, frames, width).
    """
    # Frames last, numpy crawls when the reduced axis isn't the inner one.
    frames = np.ascontiguousarray(values.transpose(0, 2, 1))
    spread = frames.max(axis=2) - frames.min(axis=2)
    return spread.max(axis=1) < CONSTANT_TOLERANCE


@dataclass(frozen=True)
class RestPose:
    position: np.ndarray
    quaternion: np.ndarray
    scale: np.ndarray
    # Nodes whose tracks never ship.
    cleared: np.ndarray

    @classmethod
    def of(cls, nodes: list[Node], cleared: set[int]) -> "RestPose":
        mask = np.zeros(len(nodes), bool)
        mask[list(cleared)] = True
        return cls(
            np.array([n.translation for n in nodes], np.float64).reshape(-1, 3),
            np.array([n.rotation for n in nodes], np.float64).reshape(-1, 4),
            np.array([n.scale for n in nodes], np.float64).reshape(-1, 3),
            mask,
        )


def pack_clip_tracks(animation: Animation, rest_pose: RestPose) -> list[Row]:
    """
    Lossless size hygiene. A still track equal to the node's rest pose is
    dropped, since three.js falls back to the node's own transform, and any
    other still track collapses to one key.
    """
    by_node: dict[int, list[Row]] = {}
    for prop, track, rests, convert in (
        ("position", animation.translation, rest_pose.position, coords.flip_z),
        ("quaternion", animation.rotation, rest_pose.quaternion, coords.conjugate_quat),
        ("scale", animation.scale, rest_pose.scale, None),
    ):
        mine = ~rest_pose.cleared[track.nodes]
        ids = track.nodes[mine]
        values = track.values[mine]
        if convert is not None:
            values = convert(values)
        rest = rests[ids]

        values = values.astype(np.float64)
        first = values[:, 0]
        off = np.abs(first - rest).max(axis=1)
        if prop == "quaternion":
            # q and -q are the same orientation, and _align picks a hemisphere
            # per track without reference to the rest pose.
            off = np.minimum(off, np.abs(first + rest).max(axis=1))
        for row in _pack_rows(ids.tolist(), prop, values, off):
            by_node.setdefault(row["node"], []).append(row)
    return [row for node in sorted(by_node) for row in by_node[node]]


def pack_morph_tracks(
    animation: Animation, channels: dict[tuple[int, int], MorphChannel]
) -> tuple[list[Row], int]:
    matched = [
        (curve, channel)
        for curve in animation.morphs
        if (channel := channels.get((curve.node, curve.name_hash))) is not None
    ]
    skipped = len(animation.morphs) - len(matched)
    if not matched:
        return [], skipped

    values = np.stack([np.asarray(curve.values, np.float64) for curve, _ in matched])
    values /= np.array([channel.full_weight for _, channel in matched])[:, None]
    values = values[..., None]
    rest = np.array([channel.rest_influence for _, channel in matched])
    rows = _pack_rows(
        [curve.node for curve, _ in matched],
        "weights",
        values,
        np.abs(values[:, 0, 0] - rest),
        [channel.index for _, channel in matched],
    )
    return rows, skipped


def find_rig_roots(nodes: list[Node], joints: set[int]) -> set[int]:
    """
    Nodes whose subtree holds every skin joint, so moving one moves the whole
    rig. A rig with no skin joints admits every node.
    """
    roots = set(range(len(nodes)))
    for joint in joints:
        chain = {joint}
        at = nodes[joint].parent
        while at is not None:
            chain.add(at)
            at = nodes[at].parent
        roots &= chain
    return roots


def find_root_node(
    nodes: list[int], depths: list[int], roots: set[int], cleared: set[int]
) -> int | None:
    """
    The shallowest translated node that carries the whole rig. A node that
    leaves a skin joint behind animates a part of the model, so its
    displacement is not root motion.
    """
    moving = [
        (depths[node], node)
        for node in nodes
        if node not in cleared and node in roots
    ]
    return min(moving)[1] if moving else None


class ClipWriter:
    """
    Streams one decoded clip to disk and forgets it.

    Holding every decoded clip costs 243 MB on r5sailinnamd010031, so the
    Animation must not outlive the call that writes it. The serialized payload
    does wait around for brotli, QUEUED_PAYLOADS of them at most.
    """

    def __init__(
        self,
        publisher: Publisher,
        nodes: list[Node],
        cleared: set[int],
        morph_channels: dict[tuple[int, int], MorphChannel],
        joints: set[int],
    ) -> None:
        self._publisher = publisher
        self._rest_pose = RestPose.of(nodes, cleared)
        self._cleared = cleared
        self._morph_channels = morph_channels
        self._depth = [measure_depth(nodes, node) for node in range(len(nodes))]
        self._rig_roots = find_rig_roots(nodes, joints)
        self._taken: set[str] = set()
        self._pending: dict[str, Future[int]] = {}
        self.unmatched = 0

    def write(
        self,
        name: str,
        layer: str | None,
        animation: Animation,
        events: list[Event],
        frame_rate: float,
    ) -> ClipFile:
        tracks = pack_clip_tracks(animation, self._rest_pose)
        morphs, skipped = pack_morph_tracks(animation, self._morph_channels)
        tracks += morphs
        self.unmatched += skipped
        relative = self._resolve_path(name, layer)
        duration = round(float(animation.times[-1]), TIME_DIGITS)
        document: ClipDoc = {"version": CLIP_VERSION, "tracks": tracks}
        if any("deltas" in track for track in tracks):
            document["packing"] = {
                "times": round_values(animation.times, TIME_DIGITS),
                "rotationBits": ROTATION_BITS,
                "valueDigits": PACKED_DIGITS,
            }
        if events:
            document["events"] = [event.as_dict() for event in events]
        payload = orjson.dumps(document)
        written = ClipFile(
            path=relative,
            duration=duration,
            tracks=len(tracks),
            morph_tracks=len(morphs),
            bytes=len(payload),
            loop=animation.loop,
            root_node=find_root_node(
                animation.translation.nodes.tolist(),
                self._depth,
                self._rig_roots,
                self._cleared,
            ),
            events=len(events),
            frame_rate=frame_rate,
        )
        self._pending[relative] = self._publisher.submit(relative, payload)
        return written

    def finish(self) -> dict[str, int]:
        """
        Wait for every clip to land, stored size by path. Raises what the first
        failed one raised.
        """
        pending, self._pending = self._pending, {}
        wait(pending.values())
        return {path: stored.result() for path, stored in pending.items()}

    def _resolve_path(self, name: str, layer: str | None) -> str:
        stem = _sanitize_filename(name)
        folder = f"{ANIM_DIR}/{_sanitize_filename(layer)}" if layer else ANIM_DIR
        relative, ordinal = f"{folder}/{stem}.json", 1
        while relative in self._taken:
            ordinal += 1
            relative = f"{folder}/{stem}_{ordinal}.json"
        if ordinal > 1:
            logger.info(f"{folder}/{stem}: clip name repeats, writing {relative}")
        self._taken.add(relative)
        return relative


_ILLEGAL = str.maketrans({"/": "_", "\\": "_", "\0": "_"})


def _sanitize_filename(name: str) -> str:
    return name.translate(_ILLEGAL)
