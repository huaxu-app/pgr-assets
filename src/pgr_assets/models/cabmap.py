import logging
import os

import msgpack

from pgr_assets.models.files import write_bytes

logger = logging.getLogger("pgr-assets")

CHECKPOINT_EVERY = 256


class CabMap:
    """
    Cab id to owning bundle, filled in as bundles load and persisted. A pointer
    fault only knows the cab id, so after an eviction this loads one bundle instead
    of walking m_Dependencies all over again.
    """

    def __init__(self, path: str) -> None:
        self._path = path
        self._map: dict[str, str] = {}
        self._unsaved = 0
        self._load()

    def get(self, cab: str) -> str | None:
        return self._map.get(cab)

    def __setitem__(self, cab: str, bundle: str) -> None:
        if self._map.get(cab) == bundle:
            return
        self._map[cab] = bundle
        self._unsaved += 1
        if self._unsaved >= CHECKPOINT_EVERY:
            self.save()

    def __len__(self) -> int:
        return len(self._map)

    def _load(self) -> None:
        try:
            with open(self._path, "rb") as f:
                loaded = msgpack.loads(f.read(), strict_map_key=False)
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:
            logger.warning(f"Ignoring unreadable cab map {self._path}: {e!r}")
            return

        if not isinstance(loaded, dict):
            logger.warning(f"Ignoring malformed cab map {self._path}")
            return
        self._map = {str(k): str(v) for k, v in loaded.items()}
        logger.debug(f"Cab map: {len(self._map)} entries from {self._path}")

    def save(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        try:
            write_bytes(self._path, msgpack.dumps(self._map) or b"")
        except OSError as e:
            logger.warning(f"Could not save cab index: {e!r}")
            return
        self._unsaved = 0
