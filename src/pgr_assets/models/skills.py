"""
Map animator states to UI skills. Normal skills first, then leap (enhanceskill).
See pgr-docs/model-pipeline/SKILL-NAMES.md.
"""

import logging
from collections.abc import Iterable, Mapping

from pgr_assets.models.tables import (
    SKILL_BUNDLE,
    SKILL_TABLE,
    Tables,
    parse_ids,
    resolve_table_path,
)

logger = logging.getLogger("pgr-assets")

CHARACTER_SKILL_BUNDLE = "assets/temp/bytes/share/character/skill.ab"
LEAP_SKILL_BUNDLE = "assets/temp/bytes/share/character/enhanceskill.ab"

StateSkills = dict[str, tuple[int, ...]]


def map_skill_states(
    character_groups: Iterable[tuple[int, list[int]]],
    group_skills: Mapping[int, list[int]],
    level_subskills: Iterable[tuple[int, list[int]]],
    animations: Mapping[int, str],
) -> dict[int, StateSkills]:
    """
    Per character, state -> UI skill ids in the character's skill list order.
    A SkillLevelId is the UI skill id followed by a two-digit level.
    """
    subskills: dict[int, list[int]] = {}
    for level_id, subs in level_subskills:
        subskills.setdefault(level_id // 100, []).extend(subs)

    result: dict[int, dict[str, list[int]]] = {}
    for character, groups in character_groups:
        states = result.setdefault(character, {})
        skills = [skill for group in groups for skill in group_skills.get(group, ())]
        for skill in skills:
            for sub in subskills.get(skill, ()):
                state = animations.get(sub)
                if state and skill not in (owners := states.setdefault(state, [])):
                    owners.append(skill)
    return {
        character: {s: tuple(o) for s, o in states.items()}
        for character, states in result.items()
        if states
    }


Rows = list[tuple]


def _read(tables: Tables, bundle: str, name: str, columns: tuple[str, ...]) -> Rows:
    """
    A skill table or a dead run. Shipping characters without skills is wrong.
    """
    try:
        if not tables.has_bundle(bundle):
            raise LookupError("bundle is in no source")
        return tables.read(bundle, name, columns)
    except Exception as error:
        raise LookupError(
            f"skills: {resolve_table_path(bundle, name)} unusable, {error}"
        ) from error


def _read_chain(tables: Tables, bundle: str, table: str) -> tuple[Rows, Rows, Rows]:
    return (
        _read(tables, bundle, f"{table}.tab.bytes", ("CharacterId", "SkillGroupId")),
        _read(tables, bundle, f"{table}group.tab.bytes", ("Id", "SkillId")),
        _read(
            tables,
            bundle,
            f"{table}leveleffect.tab.bytes",
            ("SkillLevelId", "SubSkillId"),
        ),
    )


def load_skills(tables: Tables) -> dict[int, StateSkills]:
    """
    Per character id, which UI skills each animator state plays.
    """
    character_rows, group_rows, level_rows = _read_chain(
        tables, CHARACTER_SKILL_BUNDLE, "characterskill"
    )
    skill_rows = _read(tables, SKILL_BUNDLE, SKILL_TABLE, ("Id", "Animation"))
    leap = _read_chain(tables, LEAP_SKILL_BUNDLE, "enhanceskill")
    character_rows += leap[0]
    group_rows += leap[1]
    level_rows += leap[2]

    states = map_skill_states(
        ((character, parse_ids(groups)) for character, groups in character_rows),
        {group: parse_ids(skills) for group, skills in group_rows},
        ((level_id, parse_ids(subs)) for level_id, subs in level_rows),
        {
            skill: animation.strip()
            for skill, animation in skill_rows
            if isinstance(animation, str) and animation.strip()
        },
    )
    logger.debug(f"skills: {len(states)} characters with animated skills")
    return states
