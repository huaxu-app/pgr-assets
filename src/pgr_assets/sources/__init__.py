import logging  # noqa: I001 Source must be imported before the rest

from .source import Source

from .exceptions import (
    BlobDownloadError,
    BlobNotFoundException,
    SourceError,
    SourceIndexError,
    UnknownSourceError,
)
from .gamedir import GameDirSource
from .obbstarter import ObbSource
from .patchcdn import PatchCdn, PatchCdnSource
from .pcstarter import PcStarterCdn, PcStarterSource
from .sourceset import SourceSet

logger = logging.getLogger("pgr-assets.sources")

__all__ = [
    "BlobDownloadError",
    "BlobNotFoundException",
    "GameDirSource",
    "ObbSource",
    "PatchCdn",
    "PatchCdnSource",
    "PcStarterCdn",
    "PcStarterSource",
    "Source",
    "SourceError",
    "SourceIndexError",
    "SourceSet",
    "UnknownSourceError",
]
