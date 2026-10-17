"""
The shared cubemap library on disk: one webp per cubemap under _shared/cubemaps
plus an index, kept across runs and pruned to what the built targets name.
"""

import hashlib
import logging
import os
import re
from typing import Any

from pgr_assets.models.cubemap import IMAGE_SUFFIX, Cubemap, read_cubemap
from pgr_assets.models.files import publish_json, read_json, write_bytes
from pgr_assets.models.format import (
    CUBEMAP_DIR,
    FORMAT_VERSION,
    INDEX_FILE,
    CubemapIndex,
    CubemapRow,
)
from pgr_assets.models.unity import read_pointer, resolve_asset_key

logger = logging.getLogger("pgr-assets")

_SAFE = re.compile(r"[^A-Za-z0-9._-]")


class CubemapLibrary:
    def __init__(
        self, root: str | None = None, quality: int = 0, force: bool = False
    ) -> None:
        self._directory = None if root is None else os.path.join(root, CUBEMAP_DIR)
        self._quality = quality
        self._force = force
        self._rows: dict[str, CubemapRow] = (
            {} if self._directory is None else _read_index(self._directory)
        )
        self.cubemaps: dict[str, Cubemap] = {}
        self._by_key: dict[str, str] = {}
        self._dirty = False

    def add(self, pointer: Any, where: str) -> str | None:
        texture = read_pointer(pointer, where, "_CubeMap pointer")
        if texture is None:
            return None

        key = resolve_asset_key(texture)
        existing = self._by_key.get(key)
        if existing is not None:
            return existing

        cubemap = read_cubemap(texture, key, where)
        if cubemap is None:
            return None
        return self.place(cubemap)

    def place(self, cubemap: Cubemap) -> str:
        existing = self._by_key.get(cubemap.key)
        if existing is not None:
            return existing
        cubemap.name = self._reserve(cubemap.name, cubemap.key)
        self.cubemaps[cubemap.name] = cubemap
        self._by_key[cubemap.key] = cubemap.name
        self._dirty = True
        return cubemap.name

    def write(self) -> int:
        if not self._dirty or self._directory is None:
            return 0

        directory = self._directory
        os.makedirs(directory, exist_ok=True)

        written = 0
        for name, cubemap in self.cubemaps.items():
            target = os.path.join(directory, f"{name}{IMAGE_SUFFIX}")
            row = cubemap.as_dict()
            if not self._force and self._rows.get(name) == row and os.path.exists(target):
                continue
            self._rows[name] = row
            write_bytes(target, cubemap.image)
            written += 1

        self._publish()
        self._dirty = False
        logger.info(
            f"cubemaps: {len(self.cubemaps)} used, {written} written,"
            f" {sum(len(cubemap.image) for cubemap in self.cubemaps.values()) / 1e6:.1f} MB"
            f" -> {directory}"
        )
        return written

    def prune(self, keep: set[str]) -> None:
        """
        Drop every cubemap no published glb names.
        """
        if self._directory is None or not os.path.isdir(self._directory):
            return
        gone = sorted(set(self._rows) - keep)
        for name in gone:
            del self._rows[name]
        for entry in os.listdir(self._directory):
            if entry.endswith(IMAGE_SUFFIX) and entry[: -len(IMAGE_SUFFIX)] not in self._rows:
                os.remove(os.path.join(self._directory, entry))
        self._publish()
        if gone:
            logger.info(f"cubemaps: pruned {len(gone)} no glb names")

    def _publish(self) -> None:
        index: CubemapIndex = {
            "formatVersion": FORMAT_VERSION,
            "cubemaps": dict(sorted(self._rows.items())),
        }
        assert self._directory is not None
        publish_json(os.path.join(self._directory, INDEX_FILE), index, self._quality)

    def _has_clash(self, name: str, key: str) -> bool:
        if name in self.cubemaps:
            return self.cubemaps[name].key != key
        row = self._rows.get(name)
        return row is not None and row["key"] != key

    def _reserve(self, name: str, key: str) -> str:
        safe = _SAFE.sub("_", name) or "cubemap"
        if not self._has_clash(safe, key):
            return safe
        digest = hashlib.sha1(key.encode()).hexdigest()
        for qualified in (f"{safe}-{digest[:8]}", f"{safe}-{digest}"):
            if not self._has_clash(qualified, key):
                logger.warning(
                    f"cubemap name {safe} holds another asset, writing {qualified}"
                )
                return qualified
        raise LookupError(f"cubemap name {safe} and its qualified forms are all taken")


def _read_index(directory: str) -> dict[str, CubemapRow]:
    try:
        index: CubemapIndex = read_json(os.path.join(directory, INDEX_FILE))
        rows = index["cubemaps"]
        if not all("key" in row for row in rows.values()):
            raise KeyError("key")
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, KeyError) as error:
        logger.warning(f"{directory}: cubemap index unreadable, {error}")
        return {}
    return rows
