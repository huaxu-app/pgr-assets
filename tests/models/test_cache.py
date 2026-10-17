import os
import tempfile
import unittest

from pgr_assets.models.cache import BuildCache, build_key
from pgr_assets.models.format import BUILD_FILE


class _Sources:
    def __init__(self, sha1s: dict[str, str]) -> None:
        self.sha1s = sha1s

    def bundle_sha1(self, bundle: str) -> str | None:
        return self.sha1s.get(bundle)


class BuildKeyTest(unittest.TestCase):
    def test_order_does_not_matter_and_a_missing_sha_means_no_key(self):
        a = build_key({"x.ab": "1", "y.ab": "2"})
        b = build_key({"y.ab": "2", "x.ab": "1"})
        self.assertEqual(a, b)
        self.assertNotEqual(a, build_key({"x.ab": "1", "y.ab": "3"}))
        self.assertIsNone(build_key({"x.ab": "1", "y.ab": None}))
        self.assertIsNone(build_key({}))


class BuildCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sources = _Sources({"a.ab": "1", "shared.ab": "s"})
        self.cache = BuildCache(self.sources, frozenset(["shared.ab"]))  # type: ignore[arg-type]

    def test_a_changed_shared_bundle_makes_the_target_stale(self):
        self.cache.write_marker(self.tmp.name, ["a.ab"], 0, [], "webp")
        self.sources.sha1s["shared.ab"] = "changed"
        self.assertIsNone(self.cache.fresh(self.tmp.name))

    def test_a_missing_or_broken_marker_is_not_fresh(self):
        self.assertIsNone(self.cache.fresh(self.tmp.name))
        with open(os.path.join(self.tmp.name, BUILD_FILE), "w") as handle:
            handle.write('{"key": ')
        with self.assertLogs("pgr-assets", "WARNING"):
            self.assertIsNone(self.cache.fresh(self.tmp.name))


if __name__ == "__main__":
    unittest.main()
