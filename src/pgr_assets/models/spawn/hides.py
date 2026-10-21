"""
What each context switches off before the first frame.

Fight: XRLNpc.Load hides every joint the spawn state hid, then the Born skill
hides its share, see npcstate.simulate_spawn
Menu: the UI applies a per-action node list from uimodelboneactive when a model loads.
"""

import logging
from dataclasses import dataclass

from pgr_assets.models.fashion import Fashion
from pgr_assets.models.spawn.fighttables import FightTables
from pgr_assets.models.spawn.npcstate import Facts, simulate_spawn
from pgr_assets.models.tables import Tables, normalize_model_key

logger = logging.getLogger("pgr-assets")

UI_BUNDLE = "assets/temp/bytes/client/ui.ab"
UI_TABLE = "uimodelboneactive.tab.bytes"
MENU_DEFAULT_ACTIONS = ("UiStand1", "StandAct0101")


@dataclass(frozen=True)
class ContextHides:
    fight: dict[str, tuple[str, ...]]
    menu: dict[str, dict[str, tuple[str, ...]]]

    def find_spawn_hides(self, model_id: str) -> tuple[str, ...]:
        return self.fight.get(model_id, ())

    def find_menu_hides(self, model_id: str) -> tuple[str, ...]:
        rows = self.menu.get(model_id, {})
        for action in MENU_DEFAULT_ACTIONS:
            if action in rows:
                return rows[action]
        return ()

    def find_state_hides(self, model_id: str) -> dict[str, tuple[str, ...]]:
        return self.menu.get(model_id, {})

    @classmethod
    def load(
        cls, tables: Tables, fashions: list[Fashion]
    ) -> "ContextHides":
        fight = collect_spawn_hides(FightTables.load(tables), fashions)
        menu: dict[str, dict[str, tuple[str, ...]]] = {}
        for action, model_id, names in tables.read(
            UI_BUNDLE, UI_TABLE, ("ActionId", "ModelName", "HideNodes")
        ):
            if isinstance(model_id, str) and names and (key := normalize_model_key(model_id)):
                menu.setdefault(key, {})[str(action)] = tuple(
                    n for n in names if isinstance(n, str) and n
                )
        result = cls(fight, menu)
        logger.debug(
            f"hides: {len(result.fight)} models at simulate_spawn, {len(menu)} in the menu"
        )
        return result


def collect_spawn_hides(
    tables: FightTables, fashions: list[Fashion]
) -> dict[str, tuple[str, ...]]:
    # A character's npcs are its id with one more digit on the end.
    own = {
        f.character: [n for n in tables.npcs if n.id // 10 == f.character]
        for f in fashions
    }
    fight: dict[str, set[str]] = {}
    for fashion in fashions:
        for npc in own[fashion.character]:
            facts = Facts(fashion_id=fashion.id, npc_kind=npc.kind)
            fight.setdefault(fashion.model, set()).update(
                simulate_spawn(
                    tables, npc.born_magics, facts, npc.entry_magics
                ).collect_hidden_tags()
            )
    for npc in tables.npcs:
        if npc.model_id and npc.model_id not in fight:
            fight[npc.model_id] = simulate_spawn(
                tables, npc.born_magics, Facts(npc_kind=npc.kind), npc.entry_magics
            ).collect_hidden_tags()
    return {m: tuple(sorted(t)) for m, t in fight.items() if t}
