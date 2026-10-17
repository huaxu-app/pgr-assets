import json
import os
import tempfile
import unittest

from pgr_assets.models.cubemap import Cubemap
from pgr_assets.models.format import CUBEMAP_DIR, INDEX_FILE
from pgr_assets.models.library import CubemapLibrary


def _cubemap(name: str, key: str, payload: bytes = b"mip") -> Cubemap:
    return Cubemap(
        name=name,
        key=key,
        face_size=1,
        mips=1,
        encoding="RGBM6",
        color_space="linear",
        image=payload,
    )


class CubemapLibraryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.shared = os.path.join(self.root, CUBEMAP_DIR)

    def _mip(self, name: str) -> bytes:
        with open(os.path.join(self.shared, f"{name}.webp"), "rb") as handle:
            return handle.read()

    def _index(self) -> dict:
        with open(os.path.join(self.shared, INDEX_FILE)) as handle:
            return json.load(handle)["cubemaps"]

    def test_a_different_asset_with_the_same_name_gets_its_own_file(self):
        first = CubemapLibrary(self.root)
        first.place(_cubemap("Sky", "cab-a:1", b"old"))
        first.write()

        second = CubemapLibrary(self.root)
        name = second.place(_cubemap("Sky", "cab-b:7", b"new"))
        self.assertNotEqual("Sky", name)
        self.assertTrue(name.startswith("Sky-"))
        self.assertEqual(1, second.write())
        self.assertEqual(b"old", self._mip("Sky"))
        self.assertEqual(b"new", self._mip(name))
        self.assertEqual({"Sky", name}, set(self._index()))
        self.assertEqual("cab-b:7", self._index()[name]["key"])

    def test_prune_keeps_what_a_glb_names(self):
        cubemaps = CubemapLibrary(self.root)
        cubemaps.place(_cubemap("Sky", "cab-a:1"))
        cubemaps.place(_cubemap("Sea", "cab-b:2"))
        cubemaps.write()
        cubemaps.prune({"Sky"})
        self.assertEqual({"Sky"}, set(self._index()))
        self.assertEqual({INDEX_FILE, "Sky.webp"}, set(os.listdir(self.shared)))


if __name__ == "__main__":
    unittest.main()
