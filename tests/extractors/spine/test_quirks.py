import unittest

from pgr_assets.extractors.spine.models import Spine, SpineInfo
from pgr_assets.extractors.spine.quirks import (
    GlueQuirk,
    apply_quirk,
    find_glue,
    find_quirk,
    should_skip,
)


def _spine(name, *spines):
    return Spine(name=name, spines=list(spines))


class FindQuirkTest(unittest.TestCase):
    def test_exact_match(self):
        self.assertEqual(
            {"size": (200, 200)}, find_quirk("uilivwarmactivityvinylspine")
        )

    def test_regex_autowindow(self):
        self.assertEqual({"size": (1518, 856)}, find_quirk("foo/barautowindow"))

    def test_regex_spinelogin_wildcard(self):
        self.assertEqual(
            {"size": (1920, 1080), "all_pivot": (0.5, 0.5)},
            find_quirk("spinelogin/1-99"),
        )

    def test_first_match_wins(self):
        # The specific "1-18" entry precedes the "1-*" wildcard in dict order.
        self.assertEqual(
            {"size": (1920, 1080), "all_pivot": (0.5, 0.5), "all_position": (6, 20)},
            find_quirk("spinelogin/1-18"),
        )

    def test_no_match(self):
        self.assertIsNone(find_quirk("totally/unknown/thing"))


class ApplyQuirkTest(unittest.TestCase):
    def test_all_scale_applies_to_each_spine(self):
        spine = _spine(
            "main13_spine_luna/main13_spine_luna",
            SpineInfo("a", "a"),
            SpineInfo("b", "b"),
        )
        apply_quirk(spine)
        self.assertEqual([0.65, 0.65], [s.scale for s in spine.spines])

    def test_size_sets_found_size(self):
        spine = _spine("uilivwarmactivityvinylspine", SpineInfo("a", "a"))
        apply_quirk(spine)
        self.assertEqual((200, 200), spine.found_size)

    def test_position_and_scale(self):
        spine = _spine("luolan/luolantutorial/luolantutorial", SpineInfo("a", "a"))
        apply_quirk(spine)
        self.assertEqual((0, 5), spine.spines[0].position)
        self.assertEqual(0.26, spine.spines[0].scale)

    def test_pivot(self):
        spine = _spine("uihitmousespine", SpineInfo("a", "a"))
        apply_quirk(spine)
        self.assertEqual((0.5, 0.5), spine.spines[0].pivot)

    def test_render_quirk(self):
        spine = _spine("activityspine/activityspinechunjieqishi", SpineInfo("a", "a"))
        apply_quirk(spine)
        self.assertEqual("short", spine.render_quirk)

    def test_no_quirk_leaves_spine_untouched(self):
        spine = _spine("totally/unknown/thing", SpineInfo("a", "a"))
        apply_quirk(spine)
        self.assertIsNone(spine.found_size)
        self.assertEqual(1, spine.spines[0].scale)


class GlueTest(unittest.TestCase):
    def test_should_skip_for_non_key_glue_layer(self):
        self.assertTrue(should_skip("selena/selenaactivity/selenaactivityqg"))

    def test_glue_key_itself_is_not_skipped(self):
        self.assertFalse(should_skip("selena/selenaactivity/selenaactivitybg"))

    def test_unrelated_layer_not_skipped(self):
        self.assertFalse(should_skip("something/unrelated"))

    def test_find_glue_returns_quirk(self):
        glue = find_glue("selena/selenaactivity/selenaactivitybg")
        assert glue is not None
        self.assertIsInstance(glue, GlueQuirk)
        self.assertEqual("selena/selenaactivity", glue.name)

    def test_find_glue_returns_none_for_unknown(self):
        self.assertIsNone(find_glue("nope"))


if __name__ == "__main__":
    unittest.main()
