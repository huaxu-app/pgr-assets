"""
Characters and everything else model.tab.bytes names: fight and menu contexts,
spawn hides, transitions, skills and clip events.
"""

import logging
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum

from pgr_assets.models.clips import (
    ClipInventory,
    ClipSource,
    make_clip_sources,
    make_controller_sources,
)
from pgr_assets.models.context import (
    FIGHT_CONTEXT,
    MENU_CONTEXT,
    Context,
    PartNpc,
    resolve_hidden,
    resolve_mounts,
)
from pgr_assets.models.events import (
    load_stop_anim_names,
    read_event_tables,
    resolve_event_dispatch,
)
from pgr_assets.models.fashion import index_characters, read_fashions
from pgr_assets.models.format import resolve_asset_id
from pgr_assets.models.model import Playback
from pgr_assets.models.partnpc import ROOT, PartLink, PartLinks, load_part_links
from pgr_assets.models.prefab import Node, ObjectTag, Prefab, find_node
from pgr_assets.models.registry import ModelEntry, Registry, read_paths, read_text
from pgr_assets.models.skills import StateSkills, load_skills
from pgr_assets.models.spawn.hides import ContextHides
from pgr_assets.models.tables import (
    MODEL_BUNDLE,
    NPC_BUNDLE,
    Tables,
    normalize_model_key,
)
from pgr_assets.models.transitions import (
    TransitionTables,
    load_transition_tables,
    load_transitions,
)
from pgr_assets.tables import TableRow

logger = logging.getLogger("pgr-assets")

MODEL_TABLE = "model.tab.bytes"
MODEL_COLUMNS = (
    "Id",
    "ModelPath",
    "HXModelPath",
    "ControllerPath",
    "DisplayControllerPath",
    "UiDefaultAnimationPath",
    "LevelControllerPath",
)
LAYER_TABLE = "npcanimatorlayerinfo.tab.bytes"
SPECIAL_CASE = "SpecialWeaponCase"
FIGHT_MOUNT = "WeaponCase"
MENU_MOUNT = "UiWeaponCase"


class Reach(Enum):
    # Every row of the model table.
    ALL = "all"
    # Only the models a fashion reaches, which is what a player can see.
    FASHION = "fashion"


@dataclass(frozen=True)
class CharacterEntry(ModelEntry):
    hx_model_path: str | None = None
    controller_path: str | None = None
    display_controller_path: str | None = None
    ui_default_animation_path: str | None = None
    level_controller_paths: tuple[str, ...] = field(default_factory=tuple)

    def list_clip_sources(self) -> list[ClipSource]:
        return [
            *make_controller_sources(
                self.controller_path,
                self.display_controller_path,
                *self.level_controller_paths,
            ),
            *make_clip_sources(self.ui_default_animation_path),
        ]


def read_entry(row: TableRow) -> CharacterEntry | None:
    target = read_text(row, "Id")
    model_path = read_text(row, "ModelPath")
    if target is None or model_path is None:
        return None
    return CharacterEntry(
        id=target,
        model_path=model_path,
        hx_model_path=read_text(row, "HXModelPath"),
        controller_path=read_text(row, "ControllerPath"),
        display_controller_path=read_text(row, "DisplayControllerPath"),
        ui_default_animation_path=read_text(row, "UiDefaultAnimationPath"),
        level_controller_paths=read_paths(row, "LevelControllerPath"),
    )


def load_character_registry(tables: Tables, reach: Reach) -> Registry[CharacterEntry]:
    rows = tables.read_rows(MODEL_BUNDLE, MODEL_TABLE, MODEL_COLUMNS)
    entries = [entry for row in rows if (entry := read_entry(row)) is not None]
    if len(entries) != len(rows):
        logger.warning(f"{len(rows) - len(entries)} model rows had no Id or ModelPath")
    characters = {fashion.model for fashion in read_fashions(tables)}
    if entries and not characters:
        raise LookupError("fashion to npcres to model join produced no characters")

    parts = load_part_links(tables, {entry.id for entry in entries}).targets()
    logger.debug(f"registry: {len(entries)} targets, {len(characters)} from fashion")
    if reach is Reach.FASHION:
        reached = characters.union(*(parts.get(main, ()) for main in characters))
        entries = [entry for entry in entries if entry.id in reached]
    return Registry(entries, characters, parts)


def read_model_dirs(tables: Tables) -> dict[str, str]:
    return {
        key: resolve_asset_id(path)
        for model, path in tables.read(MODEL_BUNDLE, MODEL_TABLE, ("Id", "ModelPath"))
        if (key := normalize_model_key(model)) and isinstance(path, str) and path.strip()
    }


def load_start_layers(tables: Tables) -> dict[str, str]:
    """
    The few models the game starts on a layer other than 0, by layer name.
    """
    rows = tables.read(NPC_BUNDLE, LAYER_TABLE, ("ModelId", "LayerName"))
    return {
        key: str(names[0])
        for model, names in rows
        if names and (key := normalize_model_key(model))
    }


def read_contexts(
    entry: CharacterEntry,
    nodes: Sequence[Node],
    tags: Sequence[ObjectTag],
    present: Collection[str],
    hidden_at_spawn: Collection[str],
    hidden_in_menu: Collection[str] = (),
    start_layer: str | None = None,
    fight_parts: Sequence[PartLink] = (),
    menu_parts: Sequence[PartLink] = (),
    model_dirs: Mapping[str, str] | None = None,
) -> list[Context]:
    def have(path: str | None) -> str | None:
        return path if path in present else None

    def attach(links: Sequence[PartLink]) -> tuple[PartNpc, ...]:
        found = []
        for link in links:
            node = 0 if link.bone == ROOT else find_node(nodes, link.bone)
            target = (model_dirs or {}).get(link.target)
            if node is None:
                logger.warning(f"part npc {link.target} on {entry.id}: no node {link.bone}")
            elif target is None:
                logger.warning(f"part npc {link.target} on {entry.id}: no model row")
            else:
                found.append(PartNpc(target, node))
        return tuple(found)

    fight_mounts = resolve_mounts(FIGHT_MOUNT, nodes, tags)
    special = any(n.name == SPECIAL_CASE for n in nodes)
    return [
        Context(
            FIGHT_CONTEXT,
            base=have(entry.controller_path),
            levels=tuple(p for p in entry.level_controller_paths if p in present),
            start_layer=start_layer,
            hidden=resolve_hidden(hidden_at_spawn, nodes, tags),
            mounts=fight_mounts,
            part_npcs=attach(fight_parts),
        ),
        Context(
            MENU_CONTEXT,
            base=have(entry.display_controller_path),
            clip=have(entry.ui_default_animation_path),
            hidden=resolve_hidden(hidden_in_menu, nodes, tags),
            mounts=resolve_mounts(MENU_MOUNT, nodes, tags) if special else fight_mounts,
            part_npcs=attach(menu_parts),
        ),
    ]


@dataclass(frozen=True)
class CharacterRun:
    """
    Tables read once per run that every character target consults.
    """

    hides: ContextHides
    transitions: TransitionTables
    stop_anim_names: tuple[str, ...]
    characters: dict[str, int]
    skills: dict[int, StateSkills]
    start_layers: dict[str, str]
    parts: PartLinks
    model_dirs: dict[str, str]

    def build_playback(
        self,
        tables: Tables,
        entry: CharacterEntry,
        prefab: Prefab,
        tags: list[ObjectTag],
        clips: ClipInventory,
    ) -> Playback:
        character = self.characters.get(entry.id)
        return Playback(
            contexts=read_contexts(
                entry,
                prefab.nodes,
                tags,
                clips.sources,
                self.hides.find_spawn_hides(entry.id),
                self.hides.find_menu_hides(entry.id),
                self.start_layers.get(entry.id),
                self.parts.fight.get(entry.id, ()),
                self.parts.menu.get(entry.id, ()),
                self.model_dirs,
            ),
            event_tables=read_event_tables(prefab, self.stop_anim_names),
            event_dispatch=resolve_event_dispatch(prefab),
            transitions=load_transitions(tables, entry.id, self.transitions),
            character=character,
            skills={} if character is None else self.skills.get(character, {}),
        )


@dataclass(frozen=True)
class CharacterScope:
    reach: Reach

    def load_registry(self, tables: Tables) -> Registry[CharacterEntry]:
        return load_character_registry(tables, self.reach)

    def start(self, tables: Tables) -> CharacterRun:
        fashions = read_fashions(tables)
        model_dirs = read_model_dirs(tables)
        return CharacterRun(
            hides=ContextHides.load(tables, fashions),
            transitions=load_transition_tables(tables),
            stop_anim_names=load_stop_anim_names(tables),
            characters=index_characters(fashions),
            skills=load_skills(tables),
            start_layers=load_start_layers(tables),
            parts=load_part_links(tables, model_dirs.keys()),
            model_dirs=model_dirs,
        )

    def describe(self, entry: CharacterEntry) -> str:
        return "\t".join(
            [
                entry.id,
                entry.model_path,
                entry.hx_model_path or "",
                entry.controller_path or "",
                entry.display_controller_path or "",
                entry.ui_default_animation_path or "",
                ",".join(entry.level_controller_paths),
            ]
        )
