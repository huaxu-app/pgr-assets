from collections.abc import Iterable
from dataclasses import dataclass

from pgr_assets.models.spawn import magic
from pgr_assets.models.spawn.behavior import Interpreter, Notebook
from pgr_assets.models.spawn.fighttables import FightTables
from pgr_assets.models.tables import parse_ids

# The note naming the npc itself. Actions aimed at anyone else get ignored.
SELF = "1#2001"

# Nobody is mid show at spawn.
CG_SHOW_STATE = ("DoCheckNpcShowState", "DoCheckNpcShowStateEx")

FACT_FUNCS = {
    "DoGetNpcFashionId": "fashion_id",
    "DoGetNpcKind": "npc_kind",
    "DoGetNpcWeaponFashionId": "weapon_fashion_id",
}


@dataclass(frozen=True)
class Facts:
    fashion_id: int | None = None
    npc_kind: int | None = None
    # Spawn knows no weapon fashion, so the getter comes back empty.
    weapon_fashion_id: int | None = None


NO_FACTS = Facts()


class NpcState:
    def __init__(self, tables: FightTables, facts: Facts = NO_FACTS) -> None:
        self.tables = tables
        self.facts = facts
        self.notebook = Notebook()
        self.interpreter = Interpreter(tables, self.action)
        self.buffs: dict[int, float] = {}
        self.hides: dict[str, dict[int, float]] = {}
        self._behaviors_run: set[int] = set()

    def collect_hidden_tags(self) -> set[str]:
        """
        Joints hidden with nothing scheduled to show them again.
        """
        return {
            tag for tag, by in self.hides.items() if any(d < 0 for d in by.values())
        }

    def hide(self, tag: str, kind: int, duration: float) -> None:
        self.hides.setdefault(tag, {})[kind] = duration

    def show(self, kind: int) -> None:
        for by in self.hides.values():
            by.pop(kind, None)

    def run_behavior(self, behavior_id: int, lasting: bool = True) -> None:
        if behavior_id in self._behaviors_run:
            return
        self._behaviors_run.add(behavior_id)
        self.interpreter.run_setup(behavior_id, self.notebook)
        # A zero length buff drops its behavior on the spot, so adding it again runs it again
        if not lasting:
            self._behaviors_run.discard(behavior_id)

    def action(self, name: str, parts: list[str], notebook: Notebook) -> bool | None:
        def ids(token: str) -> list[int]:
            if "#" not in token:
                return parse_ids(token)
            value = notebook.value(token)
            return [] if value is None else [int(value)]

        if name in CG_SHOW_STATE:
            return False
        # Yes, you exist. Vonnegut's form II hide opens with this
        if name == "CheckNpc":
            return parts[0] == SELF
        if name == "CheckExistBuffByKind":
            kind = notebook.value(parts[1]) if len(parts) > 1 else None
            return parts[0] == SELF and kind is not None and int(kind) in self.buffs
        if name in FACT_FUNCS:
            fact = getattr(self.facts, FACT_FUNCS[name])
            if len(parts) < 2 or parts[0] != SELF or fact is None:
                return False
            notebook.store(parts[1], float(fact))
            return True
        if name == "DoMagic":
            if len(parts) >= 4 and parts[1] == SELF:
                for magic_id in ids(parts[3]):
                    magic.apply_magic(self, magic_id)
            return True
        if name == "DoCastSkill":
            if len(parts) >= 2 and parts[0] == SELF:
                for skill_id in ids(parts[1]):
                    magic.cast_skill(self, skill_id)
            return True
        if name in ("DoRemoveBuffByKind", "DoRemoveBuffByKindEx"):
            if len(parts) >= 2 and parts[0] == SELF:
                for kind in ids(parts[1]):
                    magic.remove_kind(self, kind)
            return True
        if name == "DoAddBehavior":
            for behavior_id in (i for p in parts for i in ids(p)):
                self.run_behavior(behavior_id)
            return True
        return None


def simulate_spawn(
    tables: FightTables,
    born_magics: Iterable[int],
    facts: Facts = NO_FACTS,
    entry_magics: Iterable[int] = (),
) -> NpcState:
    """
    The state XRLNpc.Load sees: born magics applied and every setup tree they
    add run once. Then the Born skill the lead role opens a fight with
    """
    state = NpcState(tables, facts)
    for magic_id in (*born_magics, *entry_magics):
        magic.apply_magic(state, magic_id)
    return state
