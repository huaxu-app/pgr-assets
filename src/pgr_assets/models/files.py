import json
import logging
import os
import tempfile
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import BoundedSemaphore
from typing import Any

import brotli

from .format import BROTLI_SUFFIX, MANIFEST_FILE, ManifestDoc

logger = logging.getLogger("pgr-assets")

# Payloads waiting on brotli at once. At q11 the clip walk outruns the pool and
# would park a whole target's clips in the queue.
QUEUED_PAYLOADS = 8


def write_bytes(path: str, payload: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def write_json(path: str, document: object) -> None:
    write_bytes(path, json.dumps(document, indent=2).encode("utf-8"))


def dump_json(document: object) -> bytes:
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


def publish_bytes(path: str, payload: bytes, quality: int) -> int:
    """
    Brotli'd at any quality above 0. The other form is removed so a reader never
    meets a stale twin. Returns the stored size.
    """
    target, stale = (
        (path + BROTLI_SUFFIX, path) if quality else (path, path + BROTLI_SUFFIX)
    )
    stored = brotli.compress(payload, quality=quality) if quality else payload
    write_bytes(target, stored)
    if os.path.exists(stale):
        os.remove(stale)
    return len(stored)


def publish_json(path: str, document: object, quality: int) -> int:
    return publish_bytes(path, dump_json(document), quality)


def read_json(path: str) -> Any:
    """
    Whichever form is on disk. Raises FileNotFoundError when neither is.
    """
    if os.path.exists(path + BROTLI_SUFFIX):
        with open(path + BROTLI_SUFFIX, "rb") as handle:
            return json.loads(brotli.decompress(handle.read()))
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


@dataclass(frozen=True)
class Publisher:
    """
    One target's output directory. Brotli runs on the pool while the caller
    decodes the next clip.
    """

    directory: str
    quality: int
    pool: ThreadPoolExecutor
    _queued: BoundedSemaphore = field(
        default_factory=lambda: BoundedSemaphore(QUEUED_PAYLOADS)
    )

    def publish(self, name: str, payload: bytes) -> int:
        return publish_bytes(self._resolve_path(name), payload, self.quality)

    def submit(self, name: str, payload: bytes) -> Future[int]:
        path = self._resolve_path(name)
        self._queued.acquire()
        future = self.pool.submit(publish_bytes, path, payload, self.quality)
        future.add_done_callback(lambda _: self._queued.release())
        return future

    def _resolve_path(self, name: str) -> str:
        path = os.path.join(self.directory, *name.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path


def sync_target(directory: str, quality: int, pool: ThreadPoolExecutor) -> None:
    """
    Move a cached target to another quality, 0 meaning uncompressed. A file that
    fails keeps its old form and a warning, a retry next run would only fail the
    same way. Raises when the manifest itself is unreadable.
    """
    manifest_path = os.path.join(directory, MANIFEST_FILE)
    manifest: ManifestDoc = read_json(manifest_path)

    model = manifest["model"]
    names = [model] if model else []
    names += [clip["file"] for clip in manifest["clips"]]

    def convert(name: str) -> int | None:
        """
        Stored bytes, or None when the file already sits plain at quality 0 or failed.
        """
        plain = os.path.join(directory, name)
        packed = plain + BROTLI_SUFFIX
        compressed = os.path.exists(packed)
        if not quality and not compressed:
            return None
        try:
            with open(packed if compressed else plain, "rb") as handle:
                data = handle.read()
            if compressed:
                data = brotli.decompress(data)
            return publish_bytes(plain, data, quality)
        except (OSError, brotli.error) as error:
            logger.warning(f"{directory}: {name} kept as is, {error}")
            return None

    sizes = list(pool.map(convert, names))
    if model and sizes[0] is not None:
        manifest["modelStoredBytes"] = sizes[0]

    publish_json(manifest_path, manifest, quality)
