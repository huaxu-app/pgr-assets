"""
Clip inventory: which clips a target plays, by controller state or on their own,
streamed to a sink as they are read.
"""

import logging
import os
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Protocol

from pgr_assets.lazyenv import LazyEnv
from pgr_assets.models.animation import TRANSFORM_TYPE, Animation, decode_clip
from pgr_assets.models.controllers import (
    AnimatorState,
    Layer,
    StateTiming,
    hash_paths,
    read_controller,
)
from pgr_assets.models.events import Event, read_events
from pgr_assets.models.faces import Faces, StateFace
from pgr_assets.models.unity import resolve_asset_key, resolve_reader_key

logger = logging.getLogger("pgr-assets")


class SourceKind(Enum):
    CONTROLLER = "controller"
    CLIP = "clip"


@dataclass(frozen=True)
class ClipSource:
    """
    A controller or bare clip asset path a context plays from.
    """

    path: str
    kind: SourceKind

    @property
    def bundle(self) -> str:
        return f"{self.path.rsplit('/', 1)[0]}.ab"


def make_controller_sources(*paths: str | None) -> list[ClipSource]:
    return [ClipSource(path, SourceKind.CONTROLLER) for path in paths if path]


def make_clip_sources(*paths: str | None) -> list[ClipSource]:
    return [ClipSource(path, SourceKind.CLIP) for path in paths if path]


def resolve_source_stem(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


@dataclass(frozen=True)
class Coverage:
    transforms: int
    resolved: int
    by_type: Counter[int]
    by_attribute: Counter[int]


def measure_coverage(clip: Any, table: dict[int, int]) -> Coverage:
    bindings = clip.m_ClipBindingConstant.genericBindings
    transforms = [b for b in bindings if b.typeID == TRANSFORM_TYPE]
    return Coverage(
        transforms=len(transforms),
        resolved=sum(b.path in table for b in transforms),
        by_type=Counter(b.typeID for b in bindings),
        by_attribute=Counter(b.attribute for b in transforms),
    )


@dataclass(frozen=True)
class ClipFile:
    path: str
    duration: float
    tracks: int
    morph_tracks: int
    bytes: int
    loop: bool
    root_node: int | None
    events: int
    frame_rate: float
    stored_bytes: int = 0


class ClipSink(Protocol):
    """
    Where a decoded clip goes the moment it is read, so no two are held at once.
    """

    # Influence curves naming a blend shape the meshes lack.
    unmatched: int

    def write(
        self,
        name: str,
        layer: str | None,
        animation: Animation,
        events: list[Event],
        frame_rate: float,
    ) -> ClipFile: ...

    def finish(self) -> dict[str, int]:
        """
        Stored size by path once every clip has landed.
        """
        ...


@dataclass(frozen=True)
class ClipAsset:
    name: str
    coverage: Coverage
    file: ClipFile | None = None


@dataclass(frozen=True)
class ClipEntry:
    source: str
    layer: int | None
    name: str
    # The dominant child, and every child of a blend tree state.
    asset: int
    children: tuple[int, ...] = ()
    timing: StateTiming | None = None
    face: StateFace | None = None


@dataclass
class ClipInventory:
    layers: list[Layer] = field(default_factory=list)
    assets: list[ClipAsset] = field(default_factory=list)
    entries: list[ClipEntry] = field(default_factory=list)
    # Influence curves naming a blend shape the meshes lack.
    unmatched: int = 0

    @property
    def sources(self) -> set[str]:
        """
        Every controller and bare clip path that produced something.
        """
        return {layer.source for layer in self.layers} | {
            entry.source for entry in self.entries
        }


def read_clips(
    env: LazyEnv,
    target: str,
    sources: Sequence[ClipSource],
    paths: list[str],
    sink: ClipSink,
    faces: Faces | None = None,
) -> ClipInventory:
    builder = _Builder(hash_paths(paths), sink, faces)

    seen: set[str] = set()
    for source in sources:
        if source.path in seen:
            continue
        seen.add(source.path)
        if source.bundle not in env:
            logger.warning(
                f"{target}: {source.bundle} is in no source, {source.path} skipped"
            )
            continue
        try:
            env.require(source.bundle)
            obj = env.find_object(source.bundle, source.path)
            if source.kind is SourceKind.CONTROLLER:
                builder.read_controller_source(source.path, obj)
            else:
                builder.read_clip_source(source.path, obj)
        except Exception as error:  # noqa: BLE001  costs one source's clips
            logger.warning(
                f"{target}: {source.path} unusable, {type(error).__name__}: {error}"
            )

    stored = sink.finish()
    inventory = builder.inventory
    inventory.assets = [
        asset
        if asset.file is None
        else replace(
            asset, file=replace(asset.file, stored_bytes=stored[asset.file.path])
        )
        for asset in inventory.assets
    ]
    inventory.unmatched = sink.unmatched
    return inventory


@dataclass
class _Builder:
    table: dict[int, int]
    writer: ClipSink
    faces: Faces | None = None
    inventory: ClipInventory = field(default_factory=ClipInventory)
    interned: dict[str, int | None] = field(default_factory=dict)

    def read_controller_source(self, source: str, obj: Any) -> None:
        if self.faces is not None:
            self.faces.read_controller(obj)
        pointers = list(obj.m_AnimationClips)
        groups = read_controller(obj, source, self.table)
        for local, (layer, states) in enumerate(groups):
            index = len(self.inventory.layers)
            self.inventory.layers.append(layer)
            for state in states:
                entry = self._build_state_entry(source, index, local, layer, state, pointers)
                if entry is not None:
                    self.inventory.entries.append(entry)

    def _build_state_entry(
        self,
        source: str,
        index: int,
        local: int,
        layer: Layer,
        state: AnimatorState,
        pointers: list[Any],
    ) -> ClipEntry | None:
        resolved = {
            clip: self._resolve(pointers[clip], state.name, layer.name)
            for clip in dict.fromkeys(state.clips)
        }
        children = tuple(
            asset for clip in state.clips if (asset := resolved[clip]) is not None
        )
        if not children:
            return None
        dominant = resolved[state.dominant]
        return ClipEntry(
            source=source,
            layer=index,
            name=state.name,
            asset=children[0] if dominant is None else dominant,
            children=children,
            timing=state.timing,
            face=None
            if self.faces is None
            else self.faces.resolve_state_face(local, state.path_id, state.name),
        )

    def read_clip_source(self, source: str, clip: Any) -> None:
        asset = self._intern(resolve_asset_key(clip), clip, None)
        if asset is None:
            return
        self.inventory.entries.append(
            ClipEntry(source=source, layer=None, name=clip.m_Name, asset=asset)
        )

    def _resolve(self, pointer: Any, state: str, layer: str | None) -> int | None:
        """
        The asset index for a pointer, parsing the clip only on a miss.
        """
        try:
            key = resolve_reader_key(pointer.deref())
            if key in self.interned:
                return self.interned[key]
            return self._intern(key, pointer.read(), layer)
        except Exception as error:  # noqa: BLE001  a bad pointer costs one clip
            logger.warning(f"{state}: clip unreadable, {type(error).__name__}: {error}")
            return None

    def _intern(self, key: str, clip: Any, layer: str | None) -> int | None:
        """
        The asset index, or None for a clip that moves none of this rig's nodes.
        """
        if key in self.interned:
            return self.interned[key]

        measured = measure_coverage(clip, self.table)
        if measured.transforms and not measured.resolved:
            dropped = len(clip.m_Events)
            carried = f", {dropped} events with it" if dropped else ""
            logger.warning(
                f"{clip.m_Name}: binds none of this target's nodes, skipped{carried}"
            )
            self.interned[key] = None
            return None

        written = None
        try:
            written = self.writer.write(
                clip.m_Name,
                layer,
                decode_clip(clip, self.table),
                read_events(clip, self.faces),
                float(clip.m_SampleRate),
            )
        except Exception as error:  # noqa: BLE001  costs one clip
            logger.warning(
                f"{clip.m_Name}: not written, {type(error).__name__}: {error}"
            )

        index = self.interned[key] = len(self.inventory.assets)
        self.inventory.assets.append(ClipAsset(clip.m_Name, measured, written))
        return index
