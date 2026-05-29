import unittest
from typing import cast

from pgr_assets.commands import bundles as bundles_mod
from pgr_assets.commands import extract as extract_mod
from pgr_assets.commands.helpers import BundleCommandArgs, selected_bundles
from pgr_assets.commands.root import Args
from pgr_assets.sources.sourceset import SourceSet


class FakeSourceSet(SourceSet):
    def __init__(self, bundles):
        super().__init__()
        self._bundles = set(bundles)

    def list_all_bundles(self):
        return self._bundles


def _parse(argv) -> BundleCommandArgs:
    # Mirror the real entry point: parse through the top-level Args parser so we
    # exercise the same flattened namespace that __init__.main hands to func().
    # The runtime object is a top-level Args carrying the subcommand's flattened
    # attributes; cast reflects what selected_bundles actually receives.
    return cast(BundleCommandArgs, Args().parse_args(argv))


class DispatchContractTest(unittest.TestCase):
    """Guards the Tap subparser dispatch: the object handed to each ``*_cmd``
    must work with ``selected_bundles`` (see helpers.selected_bundles docstring).
    """

    def test_bundles_dispatch_resolves_selection(self):
        args = _parse(["bundles", "--preset", "global", "--output", "/tmp/o", "foo.ab"])
        # The dispatch target is bundles_cmd, and selection must run on `args`.
        # `func` is injected by Tap's set_defaults, so it's read dynamically.
        self.assertIs(getattr(args, "func"), bundles_mod.bundles_cmd)
        ss = FakeSourceSet({"foo.ab", "bar.acb"})
        self.assertEqual({"foo.ab"}, selected_bundles(args, ss))

    def test_extract_dispatch_resolves_selection(self):
        args = _parse(["extract", "--preset", "global", "--output", "/tmp/o"])
        self.assertIs(getattr(args, "func"), extract_mod.extract_cmd)
        ss = FakeSourceSet({"a.acb", "b.ab", "c.usm"})
        # --all-audio selects only the .acb bundle.
        args.all_audio = True
        self.assertEqual({"a.acb"}, selected_bundles(args, ss))


class SelectedBundlesFilterTest(unittest.TestCase):
    def _args(self, extra):
        return _parse(["bundles", "--output", "/tmp/o", *extra])

    def test_explicit_names_passed_through(self):
        ss = FakeSourceSet(set())
        self.assertEqual(
            {"x.ab", "y.acb"}, selected_bundles(self._args(["x.ab", "y.acb"]), ss)
        )

    def test_all_audio_filters_acb(self):
        ss = FakeSourceSet({"a.acb", "b.ab", "c.usm"})
        self.assertEqual({"a.acb"}, selected_bundles(self._args(["--all_audio"]), ss))

    def test_all_video_filters_usm(self):
        ss = FakeSourceSet({"a.acb", "b.ab", "c.usm"})
        self.assertEqual({"c.usm"}, selected_bundles(self._args(["--all_video"]), ss))

    def test_all_selects_everything(self):
        everything = {"a.acb", "b.ab", "c.usm"}
        ss = FakeSourceSet(everything)
        self.assertEqual(everything, selected_bundles(self._args(["--all"]), ss))


class LogLevelPositionTest(unittest.TestCase):
    """--log_level must be accepted both before and after the subcommand token, on
    every subcommand."""

    def _level(self, argv):
        return cast(Args, Args().parse_args(argv)).log_level

    def test_after_subcommand(self):
        self.assertEqual(
            "debug", self._level(["extract", "--output", "/tmp/o", "--log_level", "debug"])
        )

    def test_before_subcommand_not_clobbered(self):
        # The subparser's SUPPRESS default must not overwrite the value parsed before
        # the subcommand.
        self.assertEqual(
            "debug", self._level(["--log_level", "debug", "extract", "--output", "/tmp/o"])
        )

    def test_absent_defaults_to_none(self):
        self.assertIsNone(self._level(["extract", "--output", "/tmp/o"]))

    def test_after_subcommand_on_list_and_spines(self):
        for cmd in (["list", "--log_level", "warning"],
                    ["spines", "--output", "/tmp/o", "--log_level", "warning"]):
            self.assertEqual("warning", self._level(cmd))


if __name__ == "__main__":
    unittest.main()
