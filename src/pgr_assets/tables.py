from typing import Any, cast

import UnityPy
from UnityPy.classes import TextAsset

TableRow = dict[str, Any]


def read_script_bytes(asset: Any) -> bytes:
    return cast(TextAsset, asset).m_Script.encode("utf-8", "surrogateescape")


def read_textasset_bytes(env: UnityPy.Environment, path: str) -> bytes:
    return read_script_bytes(env.container[path].read())
