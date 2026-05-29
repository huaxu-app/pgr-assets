import unittest

from pgr_assets.versions import PATCH_KEY_SCHEME_MIN_VERSION, parse_version


class ParseVersionTest(unittest.TestCase):
    def test_parses_dotted(self):
        self.assertEqual((4, 3, 0), parse_version("4.3.0"))

    def test_parses_single_part(self):
        self.assertEqual((4,), parse_version("4"))

    def test_parses_many_parts(self):
        self.assertEqual((1, 2, 3, 4), parse_version("1.2.3.4"))

    def test_patch_key_scheme_boundary(self):
        # The patch-CDN key scheme kicks in at >= 4.3.0; the comparison in
        # SourceSet.add_patch relies on tuple ordering.
        self.assertLess(parse_version("4.2.9"), PATCH_KEY_SCHEME_MIN_VERSION)
        self.assertEqual(parse_version("4.3.0"), PATCH_KEY_SCHEME_MIN_VERSION)
        self.assertGreater(parse_version("4.4.0"), PATCH_KEY_SCHEME_MIN_VERSION)


if __name__ == "__main__":
    unittest.main()
