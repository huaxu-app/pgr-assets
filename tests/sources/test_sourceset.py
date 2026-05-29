import unittest

from pgr_assets.sources.exceptions import BlobDownloadError, BlobNotFoundException
from pgr_assets.sources.source import Source
from pgr_assets.sources.sourceset import SourceSet


class FakeSource(Source):
    """In-memory Source backed by plain dicts for resolution-order tests."""

    def __init__(
        self, *, bundles=None, blobs=None, sha1s=None, version=None, fail_blobs=None
    ):
        self._bundles = bundles or {}  # bundle name -> blob name
        self._blobs = blobs or {}  # blob name -> bytes
        self._sha1s = sha1s or {}  # bundle name -> sha1
        self._version = version
        self._fail_blobs = set(fail_blobs or ())  # hosted, but get_blob raises

    def has_blob(self, blob):
        return blob in self._blobs or blob in self._fail_blobs

    def get_blob(self, blob):
        if blob in self._fail_blobs:
            raise RuntimeError("download boom")
        return self._blobs[blob]

    def bundle_sha1(self, bundle):
        return self._sha1s.get(bundle)

    def bundle_to_blob(self, bundle):
        return self._bundles.get(bundle)

    def version(self):
        return self._version

    def resources(self):
        return {}

    def bundle_names(self):
        return list(self._bundles.keys())


def _set(*sources):
    ss = SourceSet()
    ss.sources = list(sources)
    return ss


class BundleToBlobTest(unittest.TestCase):
    def test_later_source_wins(self):
        primary = FakeSource(bundles={"b": "blob-primary"})
        patch = FakeSource(bundles={"b": "blob-patch"})
        self.assertEqual("blob-patch", _set(primary, patch).bundle_to_blob("b"))

    def test_falls_back_to_earlier_source(self):
        primary = FakeSource(bundles={"b": "blob-primary"})
        patch = FakeSource(bundles={})
        self.assertEqual("blob-primary", _set(primary, patch).bundle_to_blob("b"))

    def test_returns_none_when_unknown(self):
        self.assertIsNone(_set(FakeSource()).bundle_to_blob("missing"))


class BundleSha1Test(unittest.TestCase):
    def test_later_source_wins(self):
        primary = FakeSource(sha1s={"b": "aaa"})
        patch = FakeSource(sha1s={"b": "bbb"})
        self.assertEqual("bbb", _set(primary, patch).bundle_sha1("b"))


class FindBundleTest(unittest.TestCase):
    def test_resolves_blob_via_patch_then_fetches_from_primary(self):
        # Patch knows which blob the bundle lives in; primary holds the bytes.
        primary = FakeSource(blobs={"X": b"primary-bytes"})
        patch = FakeSource(bundles={"b": "X"}, blobs={"X": b"patch-bytes"})
        self.assertEqual(b"primary-bytes", _set(primary, patch).find_bundle("b"))

    def test_unresolvable_bundle_raises_not_found(self):
        with self.assertRaises(BlobNotFoundException):
            _set(FakeSource()).find_bundle("missing")

    def test_hosted_but_failing_download_raises_download_error(self):
        src = FakeSource(bundles={"b": "X"}, fail_blobs={"X"})
        with self.assertRaises(BlobDownloadError):
            _set(src).find_bundle("b")

    def test_blob_hosted_nowhere_raises_not_found(self):
        # Bundle resolves to a blob, but no source actually hosts that blob.
        src = FakeSource(bundles={"b": "X"})
        with self.assertRaises(BlobNotFoundException):
            _set(src).find_bundle("b")


class VersionTest(unittest.TestCase):
    def test_returns_first_non_none(self):
        s1 = FakeSource(version=None)
        s2 = FakeSource(version=(4, 3, 0))
        self.assertEqual((4, 3, 0), _set(s1, s2).version())

    def test_returns_none_when_all_unknown(self):
        self.assertIsNone(_set(FakeSource(), FakeSource()).version())


class ResourcesAssetsBytesTest(unittest.TestCase):
    def test_returns_bytes_when_present(self):
        src = FakeSource(blobs={"resources.assets": b"data"})
        self.assertEqual(b"data", _set(src)._resources_assets_bytes())

    def test_raises_when_absent(self):
        with self.assertRaises(BlobNotFoundException):
            _set(FakeSource())._resources_assets_bytes()


if __name__ == "__main__":
    unittest.main()
