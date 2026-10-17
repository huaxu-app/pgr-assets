import hashlib
import logging
import os
from collections.abc import Callable, Iterable
from typing import Any

import msgpack

logger = logging.getLogger("Source")


class Source:
    _cache_dir: str | None = None

    def cached(self, key: str, produce: Callable[[], Any]) -> Any:
        if self._cache_dir is None:
            return produce()

        path = os.path.join(
            self._cache_dir, ".meta", hashlib.sha1(key.encode()).hexdigest()
        )
        try:
            with open(path, "rb") as f:
                return msgpack.loads(f.read(), strict_map_key=False)
        except (OSError, ValueError):
            pass

        value = produce()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(msgpack.dumps(value) or b"")
        except OSError as e:
            logger.warning(f"Could not cache {key}: {e!r}")
        return value

    def has_blob(self, blob: str) -> bool:
        """Returns true if the source has the blob at the given path"""
        raise NotImplementedError()

    def get_blob(self, blob: str) -> bytes:
        """Returns the blob at the given path as binary data"""
        raise NotImplementedError()

    def bundle_sha1(self, bundle: str) -> str | None:
        """Returns the sha1 of the given blob"""
        raise NotImplementedError()

    def bundle_to_blob(self, bundle: str) -> str | None:
        """Returns the blob that contains the bundle, or None if unknown"""
        raise NotImplementedError()

    def version(self) -> tuple[int, ...] | None:
        """Returns the version of the source, or None if unknown"""
        raise NotImplementedError()

    def resources(self) -> dict[str, str]:
        """Returns a dict of blob -> path"""
        raise NotImplementedError()

    def bundle_names(self) -> Iterable[str]:
        """Returns all bundle names"""
        raise NotImplementedError()
