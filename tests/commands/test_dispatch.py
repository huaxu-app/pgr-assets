import unittest

from pgr_assets.commands import bundles as bundles_mod
from pgr_assets.commands import extract as extract_mod
from pgr_assets.commands.helpers import selected_bundles
from pgr_assets.commands.root import Args


class FakeSourceSet:
    def __init__(self, bundles):
        self._bundles = set(bundles)

    def list_all_bundles(self):
        return self._bundles


def _parse(argv):
    # Mirror the real entry point: parse through the top-level Args parser so we
    # exercise the same flattened namespace that __init__.main hands to func().
    return Args().parse_args(argv)


class DispatchContractTest(unittest.TestCase):
    """Guards the Tap subparser dispatch: the object handed to each ``*_cmd``
    must work with ``selected_bundles`` (see helpers.selected_bundles docstring).
    """

    def test_bundles_dispatch_resolves_selection(self):
        args = _parse(
            ["bundles", "--preset", "global", "--output", "/tmp/o", "foo.ab"]
        )
        # The dispatch target is bundles_cmd, and selection must run on `args`.
        self.assertIs(args.func, bundles_mod.bundles_cmd)
        ss = FakeSourceSet({"foo.ab", "bar.acb"})
        self.assertEqual({"foo.ab"}, selected_bundles(args, ss))

    def test_extract_dispatch_resolves_selection(self):
        args = _parse(["extract", "--preset", "global", "--output", "/tmp/o"])
        self.assertIs(args.func, extract_mod.extract_cmd)
        ss = FakeSourceSet({"a.acb", "b.ab", "c.usm"})
        # --all-audio selects only the .acb bundle.
        args.all_audio = True
        self.assertEqual({"a.acb"}, selected_bundles(args, ss))


class SelectedBundlesFilterTest(unittest.TestCase):
    def _args(self, extra):
        return _parse(["bundles", "--output", "/tmp/o", *extra])

    def test_explicit_names_passed_through(self):
        ss = FakeSourceSet(set())
        self.assertEqual({"x.ab", "y.acb"}, selected_bundles(self._args(["x.ab", "y.acb"]), ss))

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


if __name__ == "__main__":
    unittest.main()
