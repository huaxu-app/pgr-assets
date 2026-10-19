"""
The room chibis: dormcharacterstyle names the prefab, uimodel adds the menu rigs
that share it.
"""

import logging
import re
from collections import defaultdict
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field

from pgr_assets.models.clips import (
    ClipInventory,
    ClipSource,
    make_clip_sources,
    make_controller_sources,
)
from pgr_assets.models.context import Context, RestPolicy
from pgr_assets.models.model import Playback
from pgr_assets.models.prefab import ObjectTag, Prefab
from pgr_assets.models.registry import ModelEntry, Registry, read_text, resolve_stem
from pgr_assets.models.tables import MODEL_BUNDLE, UIMODEL_TABLE, Tables
from pgr_assets.tables import TableRow

logger = logging.getLogger("pgr-assets")

DORM_BUNDLE = "assets/temp/bytes/share/dormitory/character.ab"
DORM_STYLE_TABLE = "dormcharacterstyle.tab.bytes"
DORM_STYLE_COLUMNS = ("Id", "Model")
UIMODEL_COLUMNS = ("Id", "ModelPath", "DisplayControllerPath", "UiDefaultAnimationPath")
ROOM_PREFAB = "assets/product/role/room/prefab/"
ROOM_ANIMATION = "assets/product/role/room/animation"
DORM_CONTEXT = "dorm"
SUFFIX = re.compile(r"md\d{6}(.*)$")

# A context name to its controller and bare clip.
DormContexts = dict[str, tuple[str | None, str | None]]


@dataclass(frozen=True)
class DormEntry(ModelEntry):
    contexts: DormContexts = field(default_factory=dict)
    character: int | None = None

    def list_clip_sources(self) -> list[ClipSource]:
        return [
            *make_controller_sources(*(base for base, _ in self.contexts.values())),
            *make_clip_sources(*(clip for _, clip in self.contexts.values())),
        ]


def _read_suffix(name: str) -> str:
    found = SUFFIX.search(name.lower())
    return found.group(1) if found else ""


def read_dorm_entries(
    styles: Iterable[TableRow], uimodels: Iterable[TableRow]
) -> list[DormEntry]:
    """
    One entry per room prefab. The dorm controller is named by no table, only by
    the prefab's Animator, which always sits at this path.
    """
    paths: dict[str, str] = {}
    characters: dict[str, int] = {}
    contexts: defaultdict[str, DormContexts] = defaultdict(dict)
    for row in styles:
        path = read_text(row, "Model")
        if path is None:
            continue
        stem = resolve_stem(path)
        paths[stem] = path
        if isinstance(row.get("Id"), int):
            characters[stem] = row["Id"]
        controller = f"{ROOM_ANIMATION}/{stem}/{stem}/{stem}.controller"
        contexts[stem][DORM_CONTEXT] = (controller, None)

    for row in uimodels:
        path = read_text(row, "ModelPath")
        if path is None or not path.startswith(ROOM_PREFAB):
            continue
        stem = resolve_stem(path)
        base = read_text(row, "DisplayControllerPath")
        clip = read_text(row, "UiDefaultAnimationPath")
        name = _read_suffix(str(row.get("Id", ""))) or (
            base and _read_suffix(resolve_stem(base))
        )
        if not name:
            logger.warning(f"uimodel {row.get('Id')}: no context name, skipped")
            continue
        if name in contexts[stem]:
            logger.warning(f"{stem}: context {name} named twice, first kept")
            continue
        paths[stem] = path
        contexts[stem][name] = (base, clip)

    return [
        DormEntry(
            id=stem,
            model_path=paths[stem],
            contexts=contexts[stem],
            character=characters.get(stem),
        )
        for stem in sorted(paths)
    ]


def load_dorm_registry(tables: Tables) -> Registry[DormEntry]:
    styles = tables.read_rows(DORM_BUNDLE, DORM_STYLE_TABLE, DORM_STYLE_COLUMNS)
    uimodels = tables.read_rows(MODEL_BUNDLE, UIMODEL_TABLE, UIMODEL_COLUMNS)
    entries = read_dorm_entries(styles, uimodels)
    logger.debug(f"dorm registry: {len(entries)} targets")
    return Registry(entries)


def read_contexts(entry: DormEntry, present: Collection[str]) -> list[Context]:
    return [
        Context(
            name,
            base=base if base in present else None,
            clip=clip if clip in present else None,
            rest=RestPolicy.ENTRY,
        )
        for name, (base, clip) in entry.contexts.items()
    ]


@dataclass(frozen=True)
class DormRun:
    def build_playback(
        self,
        tables: Tables,
        entry: DormEntry,
        prefab: Prefab,
        tags: list[ObjectTag],
        clips: ClipInventory,
    ) -> Playback:
        # Only the fight loader strips clip events, and no dorm chibi goes through it.
        return Playback(
            contexts=read_contexts(entry, clips.sources),
            event_dispatch="native",
            character=entry.character,
        )


@dataclass(frozen=True)
class DormScope:
    def load_registry(self, tables: Tables) -> Registry[DormEntry]:
        return load_dorm_registry(tables)

    def start(self, tables: Tables) -> DormRun:
        return DormRun()

    def describe(self, entry: DormEntry) -> str:
        return "\t".join(
            [
                entry.id,
                entry.model_path,
                "" if entry.character is None else str(entry.character),
                ",".join(
                    f"{name}:{base or clip or ''}"
                    for name, (base, clip) in entry.contexts.items()
                ),
            ]
        )
