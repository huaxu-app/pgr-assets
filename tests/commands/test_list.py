import unittest

from pgr_assets.commands.helpers import (
    filter_bundles,
)


class FilterBundlesTest(unittest.TestCase):
    def test_substring_match(self):
        self.assertEqual(
            ["foo/lucia.ab", "foo/lucia_skin.ab"],
            filter_bundles(
                {"foo/lucia.ab", "foo/lucia_skin.ab", "foo/bambinata.ab"}, ["lucia"]
            ),
        )

    def test_case_insensitive(self):
        self.assertEqual(
            ["UI/Lucia.ab"],
            filter_bundles({"UI/Lucia.ab", "UI/other.ab"}, ["LUCIA"]),
        )

    def test_pattern_with_slash(self):
        bundles = {"ui/spine/lucia.ab", "ui/sprite/lucia.ab", "audio/lucia.acb"}
        self.assertEqual(
            ["ui/spine/lucia.ab"],
            filter_bundles(bundles, ["spine/lucia"]),
        )

    def test_multiple_patterns_are_and_combined(self):
        bundles = {"ui/spine/lucia.ab", "ui/spine/karenina.ab", "audio/lucia.acb"}
        self.assertEqual(
            ["ui/spine/lucia.ab"],
            filter_bundles(bundles, ["spine", "lucia"]),
        )


if __name__ == "__main__":
    unittest.main()
