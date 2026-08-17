import unittest
from unittest.mock import Mock

from pgr_assets.sources.exceptions import SourceIndexError
from pgr_assets.sources.patchcdn import (
    DOCUMENT_VERSION_SCAN_LIMIT,
    PatchCdnData,
    PatchCdnSource,
)


class PatchCdnUrlTest(unittest.TestCase):
    def _data(self, key=None):
        return PatchCdnData("http://cdn/prod", "com.example.app", "standalone", key=key)

    def test_config_url_includes_key_for_43_plus(self):
        url = self._data(key="ABCD1234abcd5678").config_url("4.3.0")
        self.assertIn("/ABCD1234abcd5678/", url)

    def test_config_url_omits_key_below_43(self):
        url = self._data(key="ABCD1234abcd5678").config_url("4.2.0")
        self.assertNotIn("ABCD1234abcd5678", url)

    def test_base_url_includes_key_for_43_plus(self):
        url = self._data(key="ABCD1234abcd5678").base_url("4.3.0", "9.9.9")
        self.assertIn("/ABCD1234abcd5678/", url)

    def test_base_url_omits_key_below_43(self):
        url = self._data(key="ABCD1234abcd5678").base_url("4.2.0", "9.9.9")
        self.assertNotIn("ABCD1234abcd5678", url)

    def test_key_defaults_to_none(self):
        self.assertIsNone(PatchCdnData("http://cdn", "app", "standalone").key)


class DocumentVersionScanTest(unittest.TestCase):
    def _source(self, available: set[str]) -> tuple[PatchCdnSource, Mock]:
        request = Mock(
            side_effect=lambda url, head=False: Mock(
                status_code=200
                if any(f"/{v}/matrix/index" in url for v in available)
                else 404
            )
        )
        source = PatchCdnSource.__new__(PatchCdnSource)
        source._cdn = PatchCdnData("http://cdn/prod", "com.example.app", "standalone")
        source._request = request
        return source, request

    def test_finds_the_only_published_document_version(self):
        source, _ = self._source({"4.7.3"})
        self.assertEqual(source._scan_document_version("4.7.0"), "4.7.3")

    def test_prefers_the_highest_published_document_version(self):
        source, _ = self._source({"4.6.12", "4.6.13"})
        self.assertEqual(source._scan_document_version("4.6.0"), "4.6.13")

    def test_scans_with_head_requests(self):
        source, request = self._source({"4.7.3"})
        source._scan_document_version("4.7.0")
        self.assertTrue(all(call.kwargs["head"] for call in request.call_args_list))

    def test_stops_at_the_scan_limit(self):
        source, _ = self._source({f"4.7.{DOCUMENT_VERSION_SCAN_LIMIT + 1}"})
        with self.assertRaises(SourceIndexError):
            source._scan_document_version("4.7.0")


if __name__ == "__main__":
    unittest.main()
