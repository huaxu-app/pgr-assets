import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import UnityPy

from pgr_assets.versions import parse_version

from ._index import loads_index, merge_index, read_textasset_bytes
from .exceptions import SourceIndexError
from .source import Source
from .xbuildconfig import extract_build_config

logger = logging.getLogger("GameDirSource")

_CANDIDATES = [
    (Path("PGR_Data/StreamingAssets"), Path("PGR_Data/resources.assets")),
    (Path("StreamingAssets"), Path("resources.assets")),
    (Path("."), Path("../resources.assets")),
]


@dataclass
class GameDirLayout:
    """
    Where the interesting parts of an install live.

    ``matrix_dirs`` is in precedence order, lowest first, so a later directory
    overrides an earlier one on a name collision.
    """

    matrix_dirs: list[Path]
    resources_assets: Path


def resolve_game_dir(path: str) -> GameDirLayout:
    """
    Resolve an install root, a PGR_Data dir, or a StreamingAssets dir to a layout.
    """
    root = Path(path)
    tried = []
    for streaming_rel, resources_rel in _CANDIDATES:
        streaming = (root / streaming_rel).resolve()
        index = streaming / "resource" / "matrix" / "index"
        tried.append(index)
        if not index.is_file():
            continue
        return GameDirLayout(
            matrix_dirs=_matrix_dirs(streaming),
            resources_assets=(root / resources_rel).resolve(),
        )

    raise SourceIndexError(
        f"{path} is not a game directory. Tried: " + ", ".join(str(t) for t in tried)
    )


def _matrix_dirs(streaming: Path) -> list[Path]:
    dirs = [streaming / "resource" / "matrix"]
    document = streaming / "document" / "matrix"
    if document.is_dir():
        if (document / "index").is_file():
            dirs.append(document)
        else:
            logger.warning(f"Ignoring {document}, it has no index file")
    return dirs


def _pick_index_container(names: Iterable[str]) -> str | None:
    """
    Find the index TextAsset by basename, since its directory prefix has moved
    between builds (assets/temp, assets/buildtemp).
    """
    return next((n for n in names if n.split("/")[-1] == "index.bytes"), None)


class GameDirSource(Source):
    def __init__(self, path: str):
        self._path = path
        self._layout = resolve_game_dir(path)
        self._index: dict | None = None
        self._resources: dict[str, str] | None = None
        self._version: tuple[int, ...] | None = None
        self._version_read = False

    def version(self) -> tuple[int, ...] | None:
        if self._version_read:
            return self._version
        self._version_read = True

        try:
            config = extract_build_config(self._layout.resources_assets.read_bytes())
            self._version = parse_version(config.display_version)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"No version from {self._layout.resources_assets}: {e}")
        return self._version

    def index(self) -> dict:
        if self._index is not None:
            return self._index

        index: dict = {}
        for matrix_dir in self._layout.matrix_dirs:
            index.update(self._read_index(matrix_dir / "index"))
        self._index = index
        return index

    @staticmethod
    def _read_index(path: Path) -> dict:
        env: Any = UnityPy.load(str(path))
        container = _pick_index_container(env.container.keys())
        if container is None:
            raise SourceIndexError(f"No index.bytes container in {path}")
        return merge_index(loads_index(read_textasset_bytes(env, container)))

    def resources(self) -> dict[str, str]:
        if self._resources is not None:
            return self._resources

        resources: dict[str, str] = {}
        for matrix_dir in self._layout.matrix_dirs:
            for entry in matrix_dir.iterdir():
                if entry.is_file():
                    resources[entry.name] = str(entry)
        if self._layout.resources_assets.is_file():
            resources["resources.assets"] = str(self._layout.resources_assets)

        self._resources = resources
        return resources

    def has_blob(self, blob: str) -> bool:
        return blob in self.resources()

    def get_blob(self, blob: str) -> bytes:
        return Path(self.resources()[blob]).read_bytes()

    def bundle_to_blob(self, bundle: str) -> str | None:
        index = self.index()
        try:
            return index[bundle][0]
        except KeyError:
            return None

    def bundle_sha1(self, bundle: str) -> str | None:
        index = self.index()
        try:
            return index[bundle][1]
        except KeyError:
            return None

    def bundle_names(self) -> Iterable[str]:
        return self.index().keys()

    def __str__(self):
        return f"GameDirSource({self._path})"
