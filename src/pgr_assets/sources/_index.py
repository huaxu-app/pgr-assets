from typing import Any, cast

import msgpack

from pgr_assets.tables import read_textasset_bytes

__all__ = ["loads_index", "merge_index", "read_textasset_bytes"]


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
