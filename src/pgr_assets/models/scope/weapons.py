"""
Weapons as standalone artifacts: the equipmodel prefabs, one controller per usage,
and the rotation the detail screen shows them at.
"""

import logging
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import IntEnum

from pgr_assets.models.clips import ClipInventory, ClipSource, make_controller_sources
from pgr_assets.models.context import (
    FIGHT_CONTEXT,
    MENU_CONTEXT,
    SHOW_CONTEXT,
    Context,
    RestPolicy,
    convert_rotation,
    keep_present,
)
from pgr_assets.models.events import read_bone_sync
from pgr_assets.models.model import Playback
from pgr_assets.models.prefab import ObjectTag, Prefab
from pgr_assets.models.registry import ModelEntry, Registry, resolve_stem
from pgr_assets.models.tables import Tables
from pgr_assets.tables import TableRow

logger = logging.getLogger("pgr-assets")

EQUIP_BUNDLE = "assets/temp/bytes/client/equip.ab"
SHARE_EQUIP_BUNDLE = "assets/temp/bytes/share/equip.ab"
WEAPON_FASHION_BUNDLE = "assets/temp/bytes/share/weaponfashion.ab"
WEAPON_FASHION_RES_BUNDLE = "assets/temp/bytes/client/weaponfashion.ab"
EQUIPMODEL_TABLE = "equipmodel.tab.bytes"
EQUIP_TABLE = "equip.tab.bytes"
BREAKTHROUGH_TABLE = "equipbreakthrough.tab.bytes"
EQUIPRES_TABLE = "equipres.tab.bytes"
WEAPON_FASHION_TABLE = "weaponfashion.tab.bytes"
WEAPON_FASHION_RES_TABLE = "weaponfashionres.tab.bytes"
TRANSFORM_TABLE = "equipmodeltransform.tab.bytes"
EQUIPMODEL_COLUMNS = ("Id", "ModelName", "AnimController", "UiAnimStateName")
MODEL_LISTS = (
    "ModelTransId",
    "ResonanceModelTransId1",
    "ResonanceModelTransId2",
    "ResonanceModelTransId3",
)
TRANSFORM_COLUMNS = ("IndexId", "UiName", "RotationX", "RotationY", "RotationZ")
DETAIL_SCREEN = "UiEquipDetail"

Rotation = tuple[float, float, float]


class Usage(IntEnum):
    """
    The equipmodel dict key: where the game shows the model.
    """

    MENU = 1
    FIGHT = 2
    SHOW = 3


@dataclass(frozen=True)
class WeaponEntry(ModelEntry):
    controllers: dict[int, tuple[str, ...]] = field(default_factory=dict)
    start_states: dict[int, str] = field(default_factory=dict)
    # Unity euler degrees the weapon detail screen turns the show model to.
    show_rotation: Rotation | None = None

    def list_clip_sources(self) -> list[ClipSource]:
        return make_controller_sources(
            *(path for paths in self.controllers.values() for path in paths)
        )


def read_usage_dict(row: TableRow, column: str) -> dict[int, str]:
    value = row.get(column)
    if not isinstance(value, dict):
        return {}
    return {
        int(k): v.strip() for k, v in value.items() if isinstance(v, str) and v.strip()
    }


def read_weapon_entries(
    rows: Iterable[TableRow], rotations: Mapping[str, Rotation] | None = None
) -> list[WeaponEntry]:
    paths: dict[str, str] = {}
    controllers: defaultdict[str, defaultdict[int, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    states: defaultdict[str, dict[int, str]] = defaultdict(dict)
    for row in rows:
        names = read_usage_dict(row, "ModelName")
        anims = read_usage_dict(row, "AnimController")
        starts = read_usage_dict(row, "UiAnimStateName")
        for usage, path in names.items():
            path = path.lower()
            stem = resolve_stem(path)
            paths[stem] = path
            if usage in anims:
                controllers[stem][usage].add(anims[usage].lower())
            if usage in starts:
                states[stem][usage] = starts[usage]
    return [
        WeaponEntry(
            id=stem,
            model_path=paths[stem],
            controllers={
                usage: tuple(sorted(found))
                for usage, found in sorted(controllers.get(stem, {}).items())
            },
            start_states=dict(sorted(states.get(stem, {}).items())),
            show_rotation=(rotations or {}).get(stem),
        )
        for stem in sorted(paths)
    ]


def _read_first_models(row: TableRow) -> list[int]:
    """
    The first mount of every model list, the only one the UI places.
    """
    found = []
    for column in MODEL_LISTS:
        models = row.get(column)
        if isinstance(models, list) and models and models[0]:
            found.append(models[0])
    return found


def read_weapon_classes(tables: Tables) -> list[tuple[int, int]]:
    """
    (equipmodel id, weapon class) for every equip and weapon fashion that shows it.
    """
    types = {
        row["Id"]: row["Type"]
        for row in tables.read_rows(SHARE_EQUIP_BUNDLE, EQUIP_TABLE, ("Id", "Type"))
    }
    resources = {
        row["Id"]: row
        for row in tables.read_rows(EQUIP_BUNDLE, EQUIPRES_TABLE, ("Id", *MODEL_LISTS))
    }
    pairs = []
    for row in tables.read_rows(
        SHARE_EQUIP_BUNDLE, BREAKTHROUGH_TABLE, ("EquipId", "ResId")
    ):
        kind = types.get(row["EquipId"])
        resource = resources.get(row["ResId"])
        if kind is not None and resource is not None:
            pairs.extend((model, kind) for model in _read_first_models(resource))

    fashion_types = {
        row["Id"]: row["EquipType"]
        for row in tables.read_rows(
            WEAPON_FASHION_BUNDLE, WEAPON_FASHION_TABLE, ("Id", "EquipType")
        )
    }
    for row in tables.read_rows(
        WEAPON_FASHION_RES_BUNDLE, WEAPON_FASHION_RES_TABLE, ("Id", *MODEL_LISTS)
    ):
        kind = fashion_types.get(row["Id"])
        if kind is not None:
            pairs.extend((model, kind) for model in _read_first_models(row))
    return pairs


def resolve_show_rotations(
    models: Iterable[TableRow],
    pairs: Iterable[tuple[int, int]],
    transforms: Iterable[TableRow],
) -> dict[str, Rotation]:
    """
    Show stem to its class's detail screen rotation. The game would try the model
    id as the class first, and no row is keyed that high.
    """
    stems: dict[int, str] = {}
    for row in models:
        names = read_usage_dict(row, "ModelName")
        name = names.get(Usage.SHOW) or names.get(Usage.MENU)
        if name is not None:
            stems[row["Id"]] = resolve_stem(name.lower())
    rotations = {
        row["IndexId"]: (row["RotationX"], row["RotationY"], row["RotationZ"])
        for row in transforms
        if row.get("UiName") == DETAIL_SCREEN
    }

    found: dict[str, Rotation] = {}
    for model, kind in sorted(set(pairs)):
        stem = stems.get(model)
        rotation = rotations.get(kind)
        if stem is None or rotation is None:
            continue
        if found.setdefault(stem, rotation) != rotation:
            logger.warning(f"{stem}: shown as more than one weapon class, first kept")
    return found


def load_weapon_registry(tables: Tables) -> Registry[WeaponEntry]:
    rows = tables.read_rows(EQUIP_BUNDLE, EQUIPMODEL_TABLE, EQUIPMODEL_COLUMNS)
    transforms = tables.read_rows(EQUIP_BUNDLE, TRANSFORM_TABLE, TRANSFORM_COLUMNS)
    rotations = resolve_show_rotations(rows, read_weapon_classes(tables), transforms)
    entries = read_weapon_entries(rows, rotations)
    logger.debug(f"weapon registry: {len(entries)} targets from {len(rows)} rows")
    return Registry(entries)


def read_contexts(entry: WeaponEntry, present: Collection[str]) -> list[Context]:
    def context(name: str, usage: Usage, paths: Sequence[str]) -> Context:
        found = keep_present(paths, present)
        shown = entry.show_rotation if usage is Usage.SHOW else None
        return Context(
            name,
            base=found[0] if found else None,
            levels=tuple(found[1:]),
            start_state=entry.start_states.get(usage),
            rest=RestPolicy.UI_CHAIN_END,
            rotation=None if shown is None else convert_rotation(shown),
        )

    fight = entry.controllers.get(Usage.FIGHT) or entry.controllers.get(Usage.MENU, ())
    return [
        context(FIGHT_CONTEXT, Usage.FIGHT, fight),
        context(MENU_CONTEXT, Usage.MENU, entry.controllers.get(Usage.MENU, ())),
        context(SHOW_CONTEXT, Usage.SHOW, entry.controllers.get(Usage.SHOW, ())),
    ]


@dataclass(frozen=True)
class WeaponRun:
    def build_playback(
        self,
        tables: Tables,
        entry: WeaponEntry,
        prefab: Prefab,
        tags: list[ObjectTag],
        clips: ClipInventory,
    ) -> Playback:
        return Playback(
            contexts=read_contexts(entry, clips.sources),
            bone_sync=read_bone_sync(prefab),
        )


@dataclass(frozen=True)
class WeaponScope:
    def load_registry(self, tables: Tables) -> Registry[WeaponEntry]:
        return load_weapon_registry(tables)

    def start(self, tables: Tables) -> WeaponRun:
        return WeaponRun()

    def describe(self, entry: WeaponEntry) -> str:
        return "\t".join(
            [
                entry.id,
                entry.model_path,
                ",".join(
                    f"{usage}:{path}"
                    for usage, paths in entry.controllers.items()
                    for path in paths
                ),
                ",".join(f"{u}:{s}" for u, s in entry.start_states.items()),
            ]
        )
