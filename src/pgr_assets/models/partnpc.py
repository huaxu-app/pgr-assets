"""
Models the game hangs on another model at runtime, by context. Fight reads the
part NPC tables, menus read the special UI model table.
"""

import logging
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass

from pgr_assets.models.tables import (
    CLIENT_NPC_BUNDLE,
    MODEL_BUNDLE,
    NPC_BUNDLE,
    NPC_TABLE,
    NPCPART_TABLE,
    PART_MODEL_TABLE,
    QUALITY_BUNDLE,
    QUALITY_TABLE,
    SPECIAL_UI_MODEL_TABLE,
    Tables,
    normalize_model_key,
)

logger = logging.getLogger("pgr-assets")

# The main's root instead of a named bone
ROOT = ""
DEFAULT_SCREEN = "Default"


@dataclass(frozen=True)
class PartLink:
    target: str
    bone: str


@dataclass(frozen=True)
class PartLinks:
    fight: dict[str, list[PartLink]]
    menu: dict[str, list[PartLink]]

    def targets(self) -> dict[str, set[str]]:
        found: dict[str, set[str]] = {}
        for links in (self.fight, self.menu):
            for main, parts in links.items():
                found.setdefault(main, set()).update(link.target for link in parts)
        return found


def join_fight_links(
    npc_models: Mapping[int, str],
    npc_parts: Iterable[tuple[int, int, str]],
    overrides: Iterable[tuple[int, str, str]],
    models: Collection[str],
    playable: Mapping[str, Collection[int]] | None = None,
) -> dict[str, list[PartLink]]:
    """
    playable maps a model to the ids and kinds of the player npcs wearing it. Such a
    model only takes parts hung on its own npcs, not on a boss borrowing it.
    """
    playable = playable or {}

    def owned(main_model: str, main: int) -> bool:
        return main_model not in playable or main in playable[main_model]

    rows = list(npc_parts)
    bones: dict[int, list[tuple[int, str]]] = {}
    for part, main, bone in rows:
        bones.setdefault(part, []).append((main, bone))

    # The skin's own part owns its bone, the npc row only knows one skin
    picked: dict[tuple[str, str], set[str]] = {}
    for part, main_model, part_model in overrides:
        for main, bone in bones.get(part, ()):
            if owned(main_model, main):
                picked.setdefault((main_model, bone), set()).add(part_model)
    overridden = set(picked)
    for part, main, bone in rows:
        main_model, part_model = npc_models.get(main), npc_models.get(part)
        if not main_model or not part_model or not owned(main_model, main):
            continue
        if (main_model, bone) not in overridden:
            picked.setdefault((main_model, bone), set()).add(part_model)

    for (main_model, bone), targets in picked.items():
        if len(targets) > 1 and (main_model, bone) in overridden:
            logger.warning(f"part npc: {main_model} {bone or 'root'} overridden to {sorted(targets)}")
    return _group({(main, bone, t) for (main, bone), ts in picked.items() for t in ts}, models)


def join_menu_links(
    rows: Iterable[tuple[str, str, str | None, str | None]],
    models: Collection[str],
) -> dict[str, list[PartLink]]:
    picked: set[tuple[str, str, str]] = set()
    for model, screen, main, minor in rows:
        if screen != DEFAULT_SCREEN or main is None or minor is None:
            continue
        if main != model:
            logger.warning(f"special ui model: {model} loads {main} as its main")
        picked.add((main, ROOT, minor))
    return _group(picked, models)


def _group(picked: Iterable[tuple[str, str, str]], models: Collection[str]) -> dict[str, list[PartLink]]:
    grouped: dict[str, list[PartLink]] = {}
    for main, bone, target in sorted(picked, key=lambda link: (link[1], link[2])):
        if main in models and target in models:
            grouped.setdefault(main, []).append(PartLink(target, bone))
    return grouped


def load_part_links(tables: Tables, models: Collection[str]) -> PartLinks:
    return PartLinks(_load_fight(tables, models), _load_menu(tables, models))


def _load_fight(tables: Tables, models: Collection[str]) -> dict[str, list[PartLink]]:
    needed = (
        (NPC_BUNDLE, NPCPART_TABLE),
        (CLIENT_NPC_BUNDLE, PART_MODEL_TABLE),
        (QUALITY_BUNDLE, QUALITY_TABLE),
    )
    if not all(tables.has_table(bundle, name) for bundle, name in needed):
        logger.warning("part npc tables missing, no fight part links")
        return {}

    npcs = {
        npc: (key, kind)
        for npc, model, kind in tables.read(NPC_BUNDLE, NPC_TABLE, ("Id", "ModelId", "Kind"))
        if (key := normalize_model_key(model))
    }
    npc_models = {npc: model for npc, (model, _) in npcs.items()}
    playable: dict[str, set[int]] = {}
    for (npc,) in tables.read(QUALITY_BUNDLE, QUALITY_TABLE, ("NpcId",)):
        if npc in npcs:
            model, kind = npcs[npc]
            playable.setdefault(model, set()).update((npc, kind))
    npc_parts = [
        (part, main, str(bone or "").strip())
        for part, main, bone in tables.read(
            NPC_BUNDLE, NPCPART_TABLE, ("PartNpc", "MainNpc", "RenderBoneName")
        )
    ]
    overrides = [
        (part, main_key, part_key)
        for part, main, model in tables.read(
            CLIENT_NPC_BUNDLE, PART_MODEL_TABLE, ("PartNpcId", "MainNpcModelId", "PartModelId")
        )
        if (main_key := normalize_model_key(main)) and (part_key := normalize_model_key(model))
    ]
    return join_fight_links(npc_models, npc_parts, overrides, models, playable)


def _load_menu(tables: Tables, models: Collection[str]) -> dict[str, list[PartLink]]:
    if not tables.has_table(MODEL_BUNDLE, SPECIAL_UI_MODEL_TABLE):
        logger.warning("special ui model table missing, no menu part links")
        return {}

    rows = [
        (key, str(screen), normalize_model_key(main), normalize_model_key(minor))
        for model, screen, main, minor in tables.read(
            MODEL_BUNDLE, SPECIAL_UI_MODEL_TABLE, ("ModelId", "UiName", "MainModelId", "MinorModelId")
        )
        if (key := normalize_model_key(model))
    ]
    return join_menu_links(rows, models)
