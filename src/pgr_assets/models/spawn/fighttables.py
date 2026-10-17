import logging
from dataclasses import dataclass

from pgr_assets.models.tables import (
    FIGHT,
    NPC_BUNDLE,
    NPC_TABLE,
    SKILL_BUNDLE,
    SKILL_TABLE,
    Tables,
    normalize_model_key,
    parse_ids,
)

logger = logging.getLogger("pgr-assets")


@dataclass(frozen=True, slots=True)
class TreeNode:
    kind: int
    negative: bool
    name: str
    param: str
    children: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Magic:
    name: str
    params: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Buff:
    magics: tuple[int, ...]
    duration: float
    kind: int
    covers: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Npc:
    id: int
    kind: int
    model_id: str
    born_magics: tuple[int, ...]


@dataclass(frozen=True)
class FightTables:
    npcs: list[Npc]
    prefix_roots: dict[int, int]
    nodes: dict[int, TreeNode]
    magic: dict[int, Magic]
    buffs: dict[int, Buff]
    # cast then final magics
    skills: dict[int, tuple[int, ...]]

    @classmethod
    def load(cls, tables: Tables) -> "FightTables":
        npcs = [
            Npc(i, kind or 0, normalize_model_key(model) or "", tuple(parse_ids(born)))
            for i, kind, model, born in tables.read(
                NPC_BUNDLE, NPC_TABLE, ("Id", "Kind", "ModelId", "BornMagic")
            )
        ]
        prefix_roots = {
            i: prefix or 0
            for i, prefix in tables.read(
                FIGHT + "behavior.ab", "behavior.bytes", ("Id", "PrefixRoot")
            )
        }
        nodes = {
            i: TreeNode(
                int(kind),
                bool(negative),
                name or "",
                param or "",
                tuple(children or ()),
            )
            for i, kind, negative, name, children, param in tables.read(
                FIGHT + "behavior.ab",
                "behaviornode.bytes",
                ("Id", "Type", "Negative", "Name", "Children", "Param"),
            )
        }
        magic = {
            i: Magic(name, tuple(str(p) for p in (level or [])))
            for i, name, level in tables.read(
                FIGHT + "magic.ab", "magic.bytes", ("Id", "Name", "Level")
            )
        }
        buffs = {
            i: Buff(
                tuple(m for m in (on_add, on_trigger) if m),
                float(duration),
                (parse_ids(kind) or [0])[0],
                tuple(parse_ids(cover)),
            )
            for i, on_add, on_trigger, duration, kind, cover in tables.read(
                FIGHT + "buff.ab",
                "buff.bytes",
                ("Id", "Magic", "TriggerMagic", "Duration", "Kind", "Cover"),
            )
        }
        skills = {
            i: (*parse_ids(cast), *parse_ids(final))
            for i, cast, final in tables.read(
                SKILL_BUNDLE, SKILL_TABLE, ("Id", "CastMagicIds", "FinalMagicIds")
            )
        }
        logger.debug(
            f"fight tables: {len(nodes)} behavior nodes, {len(magic)} magic rows"
        )
        return cls(npcs, prefix_roots, nodes, magic, buffs, skills)
