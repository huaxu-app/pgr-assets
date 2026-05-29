import unittest
from typing import cast
from unittest import mock

from pgr_assets.commands import list as list_mod
from pgr_assets.commands import helpers as helpers_mod
from pgr_assets.commands.helpers import (
    HIGHLIGHT,
    RESET,
    BaseArgs,
    filter_bundles,
    highlight,
)
from pgr_assets.commands.list import ListCommand
from pgr_assets.commands.root import Args


class FilterBundlesTest(unittest.TestCase):
    def test_no_patterns_returns_all_sorted(self):
        # list_all_bundles() returns a set, so sorting is what makes output stable.
        self.assertEqual(
            ["a.ab", "b.acb", "c.usm"],
            filter_bundles({"c.usm", "a.ab", "b.acb"}, []),
        )

    def test_substring_match(self):
        self.assertEqual(
            ["foo/lucia.ab", "foo/lucia_skin.ab"],
            filter_bundles({"foo/lucia.ab", "foo/lucia_skin.ab", "foo/bambinata.ab"}, ["lucia"]),
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

    def test_no_match_returns_empty(self):
        self.assertEqual([], filter_bundles({"a.ab", "b.ab"}, ["zzz"]))


class HighlightTest(unittest.TestCase):
    def test_wraps_match(self):
        self.assertEqual(
            f"ui/{HIGHLIGHT}spine{RESET}/x.ab", highlight("ui/spine/x.ab", ["spine"])
        )

    def test_preserves_original_case(self):
        self.assertEqual(f"UI/{HIGHLIGHT}Spine{RESET}.ab", highlight("UI/Spine.ab", ["spine"]))

    def test_no_match_unchanged(self):
        self.assertEqual("a/b.ab", highlight("a/b.ab", ["zzz"]))

    def test_multiple_patterns_each_highlighted(self):
        self.assertEqual(
            f"ui/{HIGHLIGHT}spine{RESET}/{HIGHLIGHT}lucia{RESET}.ab",
            highlight("ui/spine/lucia.ab", ["spine", "lucia"]),
        )

    def test_overlapping_matches_merged(self):
        # "spine" (1-6) and "inel" (3-7) overlap -> one span, no nested codes.
        self.assertEqual(f"a{HIGHLIGHT}spinel{RESET}b", highlight("aspinelb", ["spine", "inel"]))


class ListDispatchTest(unittest.TestCase):
    """The flattened top-level Args must carry the `patterns` positional through
    Tap's subparser dispatch (see helpers.selected_bundles docstring for why this
    matters)."""

    def test_patterns_parsed_onto_flattened_args(self):
        args = cast(
            ListCommand,
            Args().parse_args(["list", "--preset", "global", "lucia", "test/x.ab"]),
        )
        self.assertIs(getattr(args, "func"), list_mod.list_cmd)
        self.assertEqual(["lucia", "test/x.ab"], args.patterns)

    def test_no_patterns_defaults_to_empty(self):
        args = cast(ListCommand, Args().parse_args(["list", "--preset", "global"]))
        self.assertEqual([], args.patterns)


class DefaultPresetTest(unittest.TestCase):
    """build_source_set falls back to global when no source is configured;
    explicit flags opt out."""

    def _build(self, argv):
        args = cast(BaseArgs, Args().parse_args(["list", *argv]))
        with mock.patch.object(helpers_mod.SourceSet, "add_primary"), mock.patch.object(
            helpers_mod.SourceSet, "add_patch"
        ), mock.patch.object(
            helpers_mod.SourceSet, "version", return_value=(1, 0, 0)
        ):
            helpers_mod.build_source_set(args)
        return args

    def test_no_source_defaults_to_global(self):
        args = self._build([])
        self.assertEqual("global", args.preset)

    def test_explicit_primary_opts_out(self):
        args = self._build(["--primary", "EN_PC"])
        self.assertIsNone(args.preset)


if __name__ == "__main__":
    unittest.main()
