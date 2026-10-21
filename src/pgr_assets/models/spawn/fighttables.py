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

KEYFRAME_TABLE = "skillkeyframe.bytes"
ENTRY_ANIMATION = "Born"


def read_keyframe_magics(keys: list[str], conditions: list[str]) -> list[int]:
    """
    The Magic cells of a skill's keyframes in frame order, skipping any with a
    condition since nobody knows the answer at entry
    """
    found: list[tuple[int, int]] = []
    for i, cell in enumerate(keys):
        parts = cell.split("|")
        # A busted cell skips, it doesn't get to kill the whole run
        if len(parts) < 3 or not parts[0].lstrip("-").isdigit():
            continue
        frame, kind, magic_id = parts[:3]
        condition = conditions[i] if i < len(conditions) else "nil"
        if kind == "Magic" and condition in ("nil", "") and magic_id.isdigit():
            found.append((int(frame), int(magic_id)))
    found.sort(key=lambda f: f[0])
    return [magic_id for _, magic_id in found]


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
    # The Born skill the fight plays on entry, in the order it lands
    entry_magics: tuple[int, ...] = ()


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
        skill_rows = tables.read(
            SKILL_BUNDLE,
            SKILL_TABLE,
            ("Id", "Animation", "CastMagicIds", "FinalMagicIds"),
        )
        skills = {
            i: (*parse_ids(cast), *parse_ids(final))
            for i, _, cast, final in skill_rows
        }
        born = {
            i: (parse_ids(cast), parse_ids(final))
            for i, animation, cast, final in skill_rows
            if animation == ENTRY_ANIMATION
        }
        keyframes = {
            i: read_keyframe_magics(keys or [], conditions or [])
            for i, keys, conditions in tables.read(
                SKILL_BUNDLE, KEYFRAME_TABLE, ("Id", "Key", "Condition")
            )
            if i in born
        }
        entries = {
            i: (*cast, *keyframes.get(i, ()), *final) for i, (cast, final) in born.items()
        }
        npcs = [
            Npc(
                i,
                kind or 0,
                normalize_model_key(model) or "",
                tuple(parse_ids(born_magics)),
                tuple(m for s in parse_ids(skill_ids) for m in entries.get(s, ())),
            )
            for i, kind, model, born_magics, skill_ids in tables.read(
                NPC_BUNDLE, NPC_TABLE, ("Id", "Kind", "ModelId", "BornMagic", "SkillId")
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
        logger.debug(
            f"fight tables: {len(nodes)} behavior nodes, {len(magic)} magic rows"
        )
        return cls(npcs, prefix_roots, nodes, magic, buffs, skills)
