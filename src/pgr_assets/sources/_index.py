from typing import Any, cast

import UnityPy
import msgpack
from UnityPy.classes import TextAsset


def read_textasset_bytes(env: UnityPy.Environment, path: str) -> bytes:
    """
    Read a TextAsset's raw script bytes from a loaded bundle.

    UnityPy types container reads as a bare ``Object``; the cast tells the type
    checker this is a ``TextAsset`` so ``m_Script`` is known.
    """
    asset = cast(TextAsset, env.container[path].read())
    return asset.m_Script.encode("utf-8", "surrogateescape")


def loads_index(data: bytes) -> Any:
    return msgpack.loads(data, strict_map_key=False)


def merge_index(parsed: list) -> dict:
    """
    Flatten a parsed index into a single bundle map.

    Slot 0 is the main index. Slot 1, when populated, maps a partial name to a
    further index dict, and later partials win. Slot 2 has never been populated
    and is ignored.
    """
    index = cast(dict, parsed[0])
    partials = parsed[1] if len(parsed) > 1 else None
    if isinstance(partials, dict):
        for partial in partials.values():
            index.update(partial)
    return index
