import unittest

from pgr_assets.sources.patchcdn import PatchCdnData


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


if __name__ == "__main__":
    unittest.main()
