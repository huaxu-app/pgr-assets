import logging
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from pgr_assets.models.format import TransitionsRow
from pgr_assets.models.tables import NPC_BUNDLE, NPC_TABLE, Tables, normalize_model_key

logger = logging.getLogger("pgr-assets")

TRANSITION_BUNDLE = "assets/temp/bytes/share/fight/npc/npcanimationtransition.ab"
CONFIG_BUNDLE = "assets/temp/bytes/client/fight.ab"
CONFIG_TABLE = "fightconfig.tab.bytes"
CONFIG_KEY = "DefaultAnimationTransition"
NEW_PATH_TABLE = "newtransitionnpclut.tab.bytes"
DEFAULT_TRANSITION = 0.1
# The empty source in the table, written out as ANY.
WILDCARD = ""
ANY = "*"

Layers = dict[int, dict[str, dict[str, float]]]


class WildcardRule(Enum):
    """
    How the engine consults the wildcard source row.
    """

    # The classic path: a source with a row of its own never falls back to it.
    OWN_ROW_ONLY = "own_row_only"
    # The new path: per target, the source row first, then the wildcard.
    FALLBACK = "fallback"


@dataclass
class Transitions:
    default: float
    wildcard: WildcardRule
    layers: Layers

    def as_dict(self) -> TransitionsRow:
        """
        One lookup for every model: [from][to], then [ANY][to], then default. Only
        entries that change an answer are written, which also carries the
        engine's old path, where a source with a row of its own never falls back to the wildcard.
        """
        layers = [
            self._emit_layer(self.layers.get(index, {}))
            for index in range(max(self.layers, default=-1) + 1)
        ]
        return {"default": self.default, "layers": layers}

    def _emit_layer(
        self, buckets: dict[str, dict[str, float]]
    ) -> dict[str, dict[str, float]]:
        wildcard = buckets.get(WILDCARD, {})
        fallback = {t: d for t, d in wildcard.items() if d != self.default}
        rows = {ANY: fallback} if fallback else {}
        for source, targets in buckets.items():
            if source == WILDCARD:
                continue
            row = {}
            for target in targets.keys() | wildcard.keys():
                # A target the source's own row skips. Only the engine's new path
                # falls back to the wildcard.
                unlisted = self.default
                if self.wildcard is WildcardRule.FALLBACK:
                    unlisted = wildcard.get(target, self.default)
                want = targets.get(target, unlisted)
                if want != fallback.get(target, self.default):
                    row[target] = want
            if row:
                rows[source] = dict(sorted(row.items()))
        return rows


def index_rows(rows: Iterable[tuple[int, str, str, float]]) -> Layers:
    layers: Layers = {}
    for layer, source, target, duration in rows:
        layers.setdefault(int(layer), {}).setdefault(source or WILDCARD, {})[target] = (
            float(duration)
        )
    return layers


@dataclass(frozen=True)
class TransitionTables:
    transition_default: float
    fallback_models: frozenset[str]


def load_transition_tables(tables: Tables) -> TransitionTables:
    default = DEFAULT_TRANSITION
    if tables.has_bundle(CONFIG_BUNDLE):
        for key, value in tables.read(CONFIG_BUNDLE, CONFIG_TABLE, ("Key", "Value")):
            if key == CONFIG_KEY:
                default = float(value)
    else:
        logger.warning(
            f"{CONFIG_BUNDLE} is in no source, transitions default to {default}"
        )
    if not tables.has_bundle(TRANSITION_BUNDLE):
        logger.warning(f"{TRANSITION_BUNDLE} is in no source, no model has transitions")

    new_ids = {int(row[0]) for row in tables.read(NPC_BUNDLE, NEW_PATH_TABLE, ("Id",))}
    models = {
        key
        for npc_id, model in tables.read(NPC_BUNDLE, NPC_TABLE, ("Id", "ModelId"))
        if npc_id in new_ids and (key := normalize_model_key(model))
    }
    return TransitionTables(
        transition_default=default, fallback_models=frozenset(models)
    )


def load_transitions(
    tables: Tables, model_id: str, shared: TransitionTables
) -> Transitions | None:
    name = f"{model_id}.tab.bytes"
    if not tables.has_table(TRANSITION_BUNDLE, name):
        return None
    rows = tables.read(
        TRANSITION_BUNDLE, name, ("Layer", "State", "Target", "TransitionDuration")
    )
    return Transitions(
        shared.transition_default,
        WildcardRule.FALLBACK
        if model_id in shared.fallback_models
        else WildcardRule.OWN_ROW_ONLY,
        index_rows(rows),
    )
