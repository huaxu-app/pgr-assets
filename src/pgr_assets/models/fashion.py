"""
The fashion to npcres to model join, which is how a character reaches a model.
"""

import logging
from collections.abc import Iterable
from typing import NamedTuple

from pgr_assets.models.tables import (
    FASHION_BUNDLE,
    FASHION_TABLE,
    NPC_BUNDLE,
    NPCRES_TABLE,
    Tables,
    normalize_model_key,
)

logger = logging.getLogger("pgr-assets")

NPCRES_COLUMNS = ("Id", "ModelId")
FASHION_COLUMNS = ("Id", "CharacterId", "ResourcesId")


class Fashion(NamedTuple):
    id: int
    character: int
    model: str


def read_fashions(tables: Tables) -> list[Fashion]:
    """
    Every fashion row that resolves through fashion.ResourcesId and npcres to a model.
    """
    model_by_resource = {
        row["Id"]: key
        for row in tables.read_rows(NPC_BUNDLE, NPCRES_TABLE, NPCRES_COLUMNS)
        if isinstance(row.get("ModelId"), str) and (key := normalize_model_key(row["ModelId"]))
    }
    return [
        Fashion(row["Id"], row["CharacterId"], model_by_resource[row["ResourcesId"]])
        for row in tables.read_rows(FASHION_BUNDLE, FASHION_TABLE, FASHION_COLUMNS)
        if row.get("ResourcesId") in model_by_resource
    ]


def index_characters(fashions: Iterable[Fashion]) -> dict[str, int]:
    """
    Model id to its character, for models exactly one character reaches.
    """
    characters: dict[str, int] = {}
    conflicted: set[str] = set()
    for fashion in fashions:
        if characters.setdefault(fashion.model, fashion.character) != fashion.character:
            conflicted.add(fashion.model)
    for model in conflicted:
        logger.warning(f"characters: {model} is reached by more than one character")
        del characters[model]
    return characters
