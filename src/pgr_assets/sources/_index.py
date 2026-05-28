from typing import cast

import UnityPy
import msgpack
from UnityPy.classes import TextAsset


def read_textasset_bytes(env: UnityPy.Environment, path: str) -> bytes:
    """Read a TextAsset's raw script bytes from a loaded bundle.

    UnityPy types container reads as a bare ``Object``; the cast tells the type
    checker this is a ``TextAsset`` so ``m_Script`` is known.
    """
    asset = cast(TextAsset, env.container[path].read())
    return asset.m_Script.encode("utf-8", "surrogateescape")


def loads_index(data: bytes) -> dict:
    return msgpack.loads(data, strict_map_key=False)
