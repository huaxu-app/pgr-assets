import hashlib
import io
import logging
import os
import re
from typing import BinaryIO

from pgr_assets.models.files import write_bytes
from pgr_assets.sources import BlobDownloadError, SourceSet

logger = logging.getLogger("pgr-assets")

SHA1_LEN = 40
SHA1_HEX = re.compile(rf"[0-9a-f]{{{SHA1_LEN}}}")


def _evict_stale(path: str) -> None:
    """
    Drop stale copies of a bundle.
    """
    directory, current = os.path.split(path)
    stem = current[: -(SHA1_LEN + 1)]
    for entry in os.scandir(directory):
        if entry.name == current or not entry.name.startswith(f"{stem}."):
            continue
        if SHA1_HEX.fullmatch(entry.name[len(stem) + 1 :]):
            logger.debug(f"Evicting stale cache entry {entry.name}")
            os.remove(entry.path)


def _write(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_bytes(path, data)
    _evict_stale(path)


class BundleStore:
    """
    Content-addressed disk cache of bundle bytes.

    The index sha1 is the hash of what `find_bundle` returns, so it names the
    cache entry directly and a patched bundle lands on a new path instead of
    invalidating an old one. The old copies get swept up after.
    """

    def __init__(self, sources: SourceSet, cache_dir: str):
        self.sources = sources
        self.cache_dir = cache_dir

    def _entry(self, bundle: str) -> str | None:
        """
        Cache path of the bundle, None when the index carries no sha1 for it.
        """
        sha1 = self.sources.bundle_sha1(bundle)
        if sha1 is None:
            return None
        return os.path.join(self.cache_dir, f"{bundle}.{sha1}")

    def _fetch(self, bundle: str) -> bytes:
        data = self.sources.find_bundle(bundle)
        sha1 = self.sources.bundle_sha1(bundle)
        if sha1 is not None:
            actual = hashlib.sha1(data).hexdigest()
            if actual != sha1:
                raise BlobDownloadError(
                    f"Bundle {bundle} hashed {actual}, index says {sha1}"
                )
        return data

    def size(self, bundle: str) -> int:
        """
        On-disk size of the cached entry, 0 when it is not cached yet.
        """
        path = self._entry(bundle)
        if path is None:
            return 0
        try:
            return os.path.getsize(path)
        except OSError:
            return 0

    def ensure(self, bundle: str) -> None:
        """
        Fetch a bundle into the cache without reading it back.
        """
        path = self._entry(bundle)
        if path is not None and not os.path.exists(path):
            _write(path, self._fetch(bundle))

    def open(self, bundle: str) -> BinaryIO:
        path = self._entry(bundle)
        if path is None:
            return io.BytesIO(self._fetch(bundle))
        self.ensure(bundle)
        with open(path, "rb") as f:
            return io.BytesIO(f.read())
