import unittest
from types import SimpleNamespace

import msgpack

from pgr_assets.sources._index import loads_index, read_textasset_bytes


class _FakeEntry:
    def __init__(self, obj):
        self._obj = obj

    def read(self):
        return self._obj


class LoadsIndexTest(unittest.TestCase):
    def test_round_trips_with_int_keys(self):
        # int keys require strict_map_key=False; plain msgpack.loads would reject them.
        payload = {1: "a", 2: {3: "b"}}
        self.assertEqual(payload, loads_index(msgpack.dumps(payload)))


class ReadTextassetBytesTest(unittest.TestCase):
    def test_encodes_script_round_trip(self):
        env = SimpleNamespace(
            container={"path": _FakeEntry(SimpleNamespace(m_Script="héllo"))}
        )
        self.assertEqual(
            "héllo".encode("utf-8", "surrogateescape"),
            read_textasset_bytes(env, "path"),
        )


if __name__ == "__main__":
    unittest.main()
