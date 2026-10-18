"""
Read binary tables through the demand-loading model environment.
"""

import io
from collections.abc import Sequence
from typing import Any

from pgr_assets.converters.binarytable.table import BinaryTable
from pgr_assets.models.env import ModelEnv
from pgr_assets.tables import TableRow, read_script_bytes

FIGHT = "assets/temp/bytes/share/fight/"
NPC_BUNDLE = FIGHT + "npc.ab"
NPC_TABLE = "npc.bytes"
SKILL_BUNDLE = FIGHT + "skill.ab"
SKILL_TABLE = "skill.bytes"
NPCRES_TABLE = "npcres.tab.bytes"
NPCPART_TABLE = "npcpart.bytes"
CLIENT_NPC_BUNDLE = "assets/temp/bytes/client/fight/npc.ab"
PART_MODEL_TABLE = "partnpcmodel.tab.bytes"
SPECIAL_UI_MODEL_TABLE = "specialuimodel.tab.bytes"
FASHION_BUNDLE = "assets/temp/bytes/share/fashion.ab"
FASHION_TABLE = "fashion.tab.bytes"
MODEL_BUNDLE = "assets/temp/bytes/client/resourcelut/model.ab"
QUALITY_BUNDLE = "assets/temp/bytes/share/character/quality.ab"
QUALITY_TABLE = "characterquality.tab.bytes"

# The tables more than one loader reads. Everything else is dropped after its one
# read. The fight tables alone hold some 600 MB of rows.
SHARED = frozenset(
    {
        (NPC_BUNDLE, NPC_TABLE),
        (NPC_BUNDLE, NPCRES_TABLE),
        (SKILL_BUNDLE, SKILL_TABLE),
        (FASHION_BUNDLE, FASHION_TABLE),
    }
)


def normalize_model_key(value: Any) -> str | None:
    """
    A ModelId cell as the key every table join and ModelEntry.id use.
    """
    key = str(value or "").strip().lower()
    return key or None


def parse_ids(value: Any) -> list[int]:
    """
    Ids out of a table cell, which is an int, a '|' separated string or a list of either.
    """
    if isinstance(value, int):
        return [value] if value else []
    if isinstance(value, str):
        return [int(p) for p in value.replace("|", " ").split() if p.isdigit()]
    if isinstance(value, (list, tuple)):
        return [i for v in value for i in parse_ids(v)]
    return []


def resolve_table_path(bundle: str, name: str) -> str:
    """
    A table bundle holds its tables in the folder it's named after.
    """
    return f"{bundle.removesuffix('.ab')}/{name}"


class Tables:
    """
    The run's binary tables, each named by its file name inside the bundle. The
    SHARED ones are parsed once and kept.
    """

    def __init__(self, env: ModelEnv, version: tuple[int, ...]) -> None:
        self._env = env
        self.version = (version[0], version[1])
        self._parsed: dict[tuple[str, str], BinaryTable] = {}

    def has_bundle(self, bundle: str) -> bool:
        return bundle in self._env

    def has_table(self, bundle: str, name: str) -> bool:
        if bundle not in self._env:
            return False
        self._env.require(bundle)
        return resolve_table_path(bundle, name) in self._env.list_paths(bundle)

    def forget(self) -> None:
        """
        Drop the kept tables once the loaders are done. skill.bytes alone hogs 280 MB.
        """
        self._parsed.clear()

    def read_rows(self, bundle: str, name: str, columns: Sequence[str]) -> list[TableRow]:
        """
        The requested columns as dict rows.
        """
        return [dict(zip(columns, row)) for row in self.read(bundle, name, columns)]

    def read(self, bundle: str, name: str, columns: Sequence[str]) -> list[tuple]:
        """
        Just the requested columns, in the caller's order.
        """
        table = self._load(bundle, name)
        names = [column.name for column in table.columns]
        missing = sorted(set(columns).difference(names))
        if missing:
            raise LookupError(f"{name}: columns {missing} absent, have {names}")
        picks = [names.index(column) for column in columns]
        return [tuple(row[index] for index in picks) for row in table.rows]

    def _load(self, bundle: str, name: str) -> BinaryTable:
        table = self._parsed.get((bundle, name))
        if table is None:
            self._env.require(bundle)
            asset = self._env.find_object(bundle, resolve_table_path(bundle, name))
            table = BinaryTable(io.BytesIO(read_script_bytes(asset)), self.version)
            if (bundle, name) in SHARED:
                self._parsed[(bundle, name)] = table
        return table
