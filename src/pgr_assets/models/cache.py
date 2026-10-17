import hashlib
import json
import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass, replace

from pgr_assets.models.files import write_json
from pgr_assets.models.format import BUILD_FILE, FORMAT_VERSION, MarkerDoc
from pgr_assets.sources import SourceSet

logger = logging.getLogger("pgr-assets")


def build_key(bundles: dict[str, str | None]) -> str | None:
    if not bundles or any(sha1 is None for sha1 in bundles.values()):
        return None
    digest = hashlib.sha1(f"{FORMAT_VERSION}".encode())
    for bundle, sha1 in sorted(bundles.items()):
        digest.update(f"\n{bundle} {sha1}".encode())
    return digest.hexdigest()


@dataclass(frozen=True)
class Marker:
    key: str
    quality: int
    bundles: list[str]
    # The shared cubemaps the glb names.
    cubemaps: tuple[str, ...]
    textures: str

    @classmethod
    def read(cls, directory: str) -> "Marker":
        with open(os.path.join(directory, BUILD_FILE), encoding="utf-8") as handle:
            raw: MarkerDoc = json.load(handle)
        return cls(
            raw["key"],
            raw["quality"],
            raw["bundles"],
            tuple(raw["cubemaps"]),
            raw.get("textures", "webp"),
        )


class BuildCache:
    def __init__(self, sources: SourceSet, shared: frozenset[str]) -> None:
        self._sources = sources
        self._shared = shared

    def fresh(self, directory: str) -> Marker | None:
        """
        The directory's marker when its key still matches the sources, else None.
        """
        try:
            marker = Marker.read(directory)
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError) as error:
            logger.warning(f"{directory}: build marker unreadable, {error!r}")
            return None
        bundles = sorted(set(marker.bundles) | self._shared)
        if self._hash_key(bundles) != marker.key:
            return None
        return replace(marker, bundles=bundles)

    def write_marker(
        self,
        directory: str,
        bundles: Iterable[str],
        quality: int,
        cubemaps: Iterable[str],
        textures: str,
    ) -> None:
        """
        Raises LookupError when a bundle has no sha1: an unkeyed build is no target.
        """
        used = sorted(set(bundles) | self._shared)
        key = self._hash_key(used)
        if key is None:
            missing = [b for b in used if self._sources.bundle_sha1(b) is None]
            raise LookupError(f"no sha1 for {missing}, marker not written")
        marker: MarkerDoc = {
            "key": key,
            "quality": quality,
            "bundles": used,
            "cubemaps": sorted(set(cubemaps)),
            "textures": textures,
        }
        write_json(os.path.join(directory, BUILD_FILE), marker)

    def _hash_key(self, bundles: Iterable[str]) -> str | None:
        return build_key({b: self._sources.bundle_sha1(b) for b in bundles})
