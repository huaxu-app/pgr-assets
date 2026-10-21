"""
Characters and everything else model.tab.bytes names, plus the menu-only
prefabs uimodel.tab.bytes adds: fight and menu contexts, one per uimodel row,
spawn hides, transitions, skills and clip events
"""

import logging
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
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
from pgr_assets.models.format import ROLE_PREFIX, resolve_asset_id
from pgr_assets.models.model import Playback
from pgr_assets.models.partnpc import ROOT, PartLink, PartLinks, load_part_links
from pgr_assets.models.prefab import Node, ObjectTag, Prefab, find_node
from pgr_assets.models.registry import (
    ModelEntry,
    Registry,
    read_paths,
    read_text,
    resolve_stem,
)
from pgr_assets.models.skills import StateSkills, load_skills
from pgr_assets.models.spawn.hides import ContextHides
from pgr_assets.models.tables import (
    MODEL_BUNDLE,
    NPC_BUNDLE,
    UIMODEL_TABLE,
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
UIMODEL_COLUMNS = (
    "Id",
    "ModelPath",
    "HXModelPath",
    "ControllerPath",
    "DisplayControllerPath",
    "UiDefaultAnimationPath",
    "HideNodeName",
)
# Weapons, dorm chibis, DLC chips and scene props in uimodel belong to other scopes or none
UI_PREFAB = ROLE_PREFIX + "charaterprefab/"
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
class UiRow:
    """
    One uimodel row on its prefab: a UI presentation with its own idle and hides
    """

    id: str
    display_controller_path: str | None = None
    ui_default_animation_path: str | None = None
    # Raw GameObject names, the engine matches them case and all
    hide_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class CharacterEntry(ModelEntry):
    hx_model_path: str | None = None
    controller_path: str | None = None
    display_controller_path: str | None = None
    ui_default_animation_path: str | None = None
    level_controller_paths: tuple[str, ...] = field(default_factory=tuple)
    ui_rows: tuple[UiRow, ...] = ()

    def list_clip_sources(self) -> list[ClipSource]:
        return [
            *make_controller_sources(
                self.controller_path,
                self.display_controller_path,
                *self.level_controller_paths,
            ),
            *make_clip_sources(self.ui_default_animation_path),
            *make_controller_sources(*(r.display_controller_path for r in self.ui_rows)),
            *make_clip_sources(*(r.ui_default_animation_path for r in self.ui_rows)),
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


def read_ui_row(row: TableRow) -> UiRow | None:
    row_id = read_text(row, "Id")
    if row_id is None:
        return None
    names = row.get("HideNodeName")
    return UiRow(
        id=row_id,
        display_controller_path=read_text(row, "DisplayControllerPath"),
        ui_default_animation_path=read_text(row, "UiDefaultAnimationPath"),
        hide_names=tuple(n for n in names or () if isinstance(n, str) and n),
    )


def attach_ui_rows(
    rows: Iterable[TableRow], known: Collection[CharacterEntry]
) -> list[CharacterEntry]:
    """
    Every uimodel row onto the prefab it names. A prefab only uimodel names becomes
    an entry keyed on its stem, read from its first row, since the row Id often
    names a sibling prefab
    """
    by_path: dict[str, list[UiRow]] = {}
    firsts: dict[str, CharacterEntry] = {}
    for row in rows:
        entry = read_entry(row)
        ui = read_ui_row(row)
        if entry is None or ui is None or not entry.model_path.startswith(UI_PREFAB):
            continue
        by_path.setdefault(entry.model_path, []).append(ui)
        firsts.setdefault(entry.model_path, entry)

    paths = {entry.model_path for entry in known}
    ids = {entry.id for entry in known}
    found = [replace(e, ui_rows=tuple(by_path.get(e.model_path, ()))) for e in known]
    added: set[str] = set()
    for path, first in firsts.items():
        if path in paths:
            continue
        stem = resolve_stem(path)
        if stem in ids or stem in added:
            logger.warning(f"uimodel prefab {path} shares stem {stem}, skipped")
            continue
        added.add(stem)
        found.append(replace(first, id=stem, ui_rows=tuple(by_path[path])))
    return found


def pick_default_context(
    model_path: str, rows: Collection[str], names: Collection[str]
) -> str:
    """
    The row the game shows for the bare prefab name, else its UI row, else the
    first numbered one, else the model table's own menu. A row that went
    missing was a copy of menu, so menu it is
    """
    stem = resolve_stem(model_path)
    for wanted in (stem, f"{stem}ui", f"{stem}ui1"):
        if wanted in rows:
            return wanted if wanted in names else MENU_CONTEXT
    return MENU_CONTEXT


def load_character_registry(tables: Tables, reach: Reach) -> Registry[CharacterEntry]:
    rows = tables.read_rows(MODEL_BUNDLE, MODEL_TABLE, MODEL_COLUMNS)
    entries = [entry for row in rows if (entry := read_entry(row)) is not None]
    if len(entries) != len(rows):
        logger.warning(f"{len(rows) - len(entries)} model rows had no Id or ModelPath")
    uimodels = tables.read_rows(MODEL_BUNDLE, UIMODEL_TABLE, UIMODEL_COLUMNS)
    entries = attach_ui_rows(uimodels, entries)
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
    state_hides: Mapping[str, Collection[str]] | None = None,
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
    menu_mounts = resolve_mounts(MENU_MOUNT, nodes, tags) if special else fight_mounts
    state_hidden = {
        state: found
        for state, names in (state_hides or {}).items()
        if (found := resolve_hidden(names, nodes, tags))
    }
    menu = Context(
        MENU_CONTEXT,
        base=have(entry.display_controller_path),
        clip=have(entry.ui_default_animation_path),
        hidden=resolve_hidden(hidden_in_menu, nodes, tags),
        state_hidden=state_hidden,
        mounts=menu_mounts,
        part_npcs=attach(menu_parts),
    )
    contexts = [
        Context(
            FIGHT_CONTEXT,
            base=have(entry.controller_path),
            levels=tuple(p for p in entry.level_controller_paths if p in present),
            start_layer=start_layer,
            hidden=resolve_hidden(hidden_at_spawn, nodes, tags),
            mounts=fight_mounts,
            part_npcs=attach(fight_parts),
        ),
        menu,
    ]
    tag_names = {tag.name for tag in tags}
    for row in entry.ui_rows:
        if any(context.name == row.id for context in contexts):
            logger.warning(f"{entry.id}: context {row.id} named twice, first kept")
            continue
        # An empty tag row is the engine's answer, only a name nothing carries is a miss
        missed = [
            n
            for n in row.hide_names
            if n not in tag_names and find_node(nodes, n) is None
        ]
        if missed:
            logger.warning(f"{entry.id}: {row.id} hides {missed}, not on the prefab")
        context = Context(
            row.id,
            base=have(row.display_controller_path),
            clip=have(row.ui_default_animation_path),
            hidden=resolve_hidden(row.hide_names, nodes, tags),
            mounts=menu_mounts,
            part_npcs=attach(menu_parts),
        )
        # Half the boss UI rows are the model row again with a UI on the end, one look not two
        if replace(context, name=MENU_CONTEXT) != menu:
            contexts.append(context)
    return contexts


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
        contexts = read_contexts(
            entry,
            prefab.nodes,
            tags,
            clips.sources,
            self.hides.find_spawn_hides(entry.id),
            self.hides.find_menu_hides(entry.id),
            self.hides.find_state_hides(entry.id),
            self.start_layers.get(entry.id),
            self.parts.fight.get(entry.id, ()),
            self.parts.menu.get(entry.id, ()),
            self.model_dirs,
        )
        return Playback(
            contexts=contexts,
            event_tables=read_event_tables(prefab, self.stop_anim_names),
            event_dispatch=resolve_event_dispatch(prefab),
            transitions=load_transitions(tables, entry.id, self.transitions),
            character=character,
            skills={} if character is None else self.skills.get(character, {}),
            default_context=pick_default_context(
                entry.model_path,
                {row.id for row in entry.ui_rows},
                {context.name for context in contexts},
            ),
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
                ",".join(row.id for row in entry.ui_rows),
            ]
        )
