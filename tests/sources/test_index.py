import unittest
from types import SimpleNamespace
from typing import Any, cast

import msgpack

from pgr_assets.sources._index import loads_index, merge_index, read_textasset_bytes


class _FakeEntry:
    def __init__(self, obj):
        self._obj = obj

    def read(self):
        return self._obj


class LoadsIndexTest(unittest.TestCase):
    def test_round_trips_with_int_keys(self):
        # int keys require strict_map_key=False; plain msgpack.loads would reject them.
        payload = {1: "a", 2: {3: "b"}}
        self.assertEqual(payload, loads_index(cast(bytes, msgpack.dumps(payload))))


class ReadTextassetBytesTest(unittest.TestCase):
    def test_encodes_script_round_trip(self):
        env = SimpleNamespace(
            container={"path": _FakeEntry(SimpleNamespace(m_Script="héllo"))}
        )
        self.assertEqual(
            "héllo".encode("utf-8", "surrogateescape"),
            read_textasset_bytes(cast(Any, env), "path"),
        )


class MergeIndexTest(unittest.TestCase):
    def test_returns_main_index_when_no_partials(self):
        self.assertEqual({"a": 1}, merge_index([{"a": 1}, None, None]))

    def test_merges_partial_index_values(self):
        # Slot 1 maps a partial *name* to a partial index, so the values are
        # merged, not the outer dict itself.
        parsed = [{"a": 1}, {"first": {"b": 2}, "second": {"c": 3}}, None]
        self.assertEqual({"a": 1, "b": 2, "c": 3}, merge_index(parsed))

    def test_later_partials_win(self):
        parsed = [{"a": 1}, {"first": {"a": 2}, "second": {"a": 3}}, None]
        self.assertEqual({"a": 3}, merge_index(parsed))


if __name__ == "__main__":
    unittest.main()
