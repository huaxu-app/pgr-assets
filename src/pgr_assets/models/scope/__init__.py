"""
A scope is one kind of target: which table names it, what it plays, how it is
described. The command picks one by name.
"""

from typing import Protocol

from pgr_assets.models.clips import ClipInventory
from pgr_assets.models.model import Playback
from pgr_assets.models.prefab import ObjectTag, Prefab
from pgr_assets.models.registry import ModelEntry, Registry
from pgr_assets.models.scope.characters import CharacterScope, Reach
from pgr_assets.models.scope.dorm import DormScope
from pgr_assets.models.scope.weapons import WeaponScope
from pgr_assets.models.tables import Tables


class Run[E: ModelEntry](Protocol):
    """
    Tables read once per run, and the playback they give each target.
    """

    def build_playback(
        self,
        tables: Tables,
        entry: E,
        prefab: Prefab,
        tags: list[ObjectTag],
        clips: ClipInventory,
    ) -> Playback: ...


class Scope[E: ModelEntry](Protocol):
    def load_registry(self, tables: Tables) -> Registry[E]: ...

    def start(self, tables: Tables) -> Run[E]: ...

    def describe(self, entry: E) -> str: ...


SCOPES: dict[str, Scope] = {
    "all": CharacterScope(Reach.ALL),
    "characters": CharacterScope(Reach.FASHION),
    "weapons": WeaponScope(),
    "dorm": DormScope(),
}
