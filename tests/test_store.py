import hashlib
import os
import tempfile
import unittest
from unittest import mock

from pgr_assets.sources import BlobDownloadError
from pgr_assets.store import BundleStore


class FakeSources:
    """
    Stands in for SourceSet: a bundle map plus a call counter.
    """

    def __init__(self, bundles: dict[str, bytes], sha1s: dict[str, str] | None = None):
        self._bundles = bundles
        self._sha1s = (
            sha1s
            if sha1s is not None
            else {n: hashlib.sha1(d).hexdigest() for n, d in bundles.items()}
        )
        self.calls: list[str] = []

    def bundle_sha1(self, bundle: str) -> str | None:
        return self._sha1s.get(bundle)

    def find_bundle(self, bundle: str) -> bytes:
        self.calls.append(bundle)
        return self._bundles[bundle]


class BundleStoreTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.cache_dir = self._dir.name

    def store(self, sources) -> BundleStore:
        return BundleStore(sources, self.cache_dir)  # type: ignore[arg-type]

    def test_fetches_on_miss_and_serves_from_cache_after(self):
        sources = FakeSources({"a.ab": b"hello"})
        store = self.store(sources)

        self.assertEqual(b"hello", store.open("a.ab").read())
        self.assertEqual(b"hello", store.open("a.ab").read())

        self.assertEqual(["a.ab"], sources.calls)

    def test_sha1_mismatch_raises_and_does_not_cache(self):
        sources = FakeSources({"a.ab": b"hello"}, sha1s={"a.ab": "0" * 40})
        store = self.store(sources)

        with self.assertRaises(BlobDownloadError):
            store.open("a.ab")

        self.assertEqual([], self._cached_files())
        with self.assertRaises(BlobDownloadError):
            store.open("a.ab")

    def test_bundle_without_an_index_sha1_is_served_uncached(self):
        sources = FakeSources({"a.ab": b"hello"}, sha1s={})
        store = self.store(sources)

        self.assertEqual(b"hello", store.open("a.ab").read())
        self.assertEqual(b"hello", store.open("a.ab").read())

        self.assertEqual(["a.ab", "a.ab"], sources.calls)
        self.assertEqual([], self._cached_files())

    def test_updated_bundle_replaces_the_previous_revision(self):
        old = FakeSources({"a.ab": b"hello"})
        self.store(old).ensure("a.ab")
        self.assertEqual(1, len(self._cached_files()))

        new = FakeSources({"a.ab": b"hello v2"})
        self.store(new).ensure("a.ab")

        cached = self._cached_files()
        self.assertEqual(1, len(cached))
        self.assertTrue(cached[0].endswith(new.bundle_sha1("a.ab") or ""))

    def test_eviction_leaves_other_bundles_alone(self):
        sources = FakeSources({"a.ab": b"hello", "a.ab.extra": b"other"})
        store = self.store(sources)
        store.ensure("a.ab")
        store.ensure("a.ab.extra")

        self.store(FakeSources({"a.ab": b"hello v2"})).ensure("a.ab")

        self.assertEqual(2, len(self._cached_files()))

    def test_interrupted_write_leaves_no_partial_entry(self):
        store = self.store(FakeSources({"a.ab": b"hello"}))
        with (
            mock.patch("os.replace", side_effect=OSError("disk full")),
            self.assertRaises(OSError),
        ):
            store.ensure("a.ab")

        self.assertEqual([], self._cached_files())

    def _cached_files(self) -> list[str]:
        return [f for _root, _dirs, files in os.walk(self.cache_dir) for f in files]


if __name__ == "__main__":
    unittest.main()
