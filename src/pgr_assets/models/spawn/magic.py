from typing import TYPE_CHECKING

from pgr_assets.models.tables import parse_ids

if TYPE_CHECKING:
    from pgr_assets.models.spawn.npcstate import NpcState

HIDE_FUNCS = ("HideJoint", "HideJoints")


def apply_magic(
    world: "NpcState", magic_id: int, kind: int = 0, duration: float = -1.0
) -> None:
    magic = world.tables.magic.get(magic_id)
    if magic is None:
        return
    if magic.name in HIDE_FUNCS:
        for tag in (j for p in magic.params for j in p.split(";") if j):
            world.hide(tag, kind, duration)
    elif magic.name == "AddBuff":
        for buff_id in parse_ids(magic.params):
            apply_buff(world, buff_id)
    elif magic.name == "AddBehavior":
        for behavior_id in parse_ids(magic.params):
            world.run_behavior(behavior_id)


def apply_buff(world: "NpcState", buff_id: int) -> None:
    buff = world.tables.buffs.get(buff_id)
    if buff is None:
        return
    for covered in buff.covers:
        remove_kind(world, covered)
    world.buffs[buff.kind] = buff.duration
    for magic_id in buff.magics:
        apply_magic(world, magic_id, buff.kind, buff.duration)


def remove_kind(world: "NpcState", kind: int) -> None:
    world.buffs.pop(kind, None)
    world.show(kind)


def cast_skill(world: "NpcState", skill_id: int) -> None:
    for magic_id in world.tables.skills.get(skill_id, ()):
        apply_magic(world, magic_id)
