import unittest

from pgr_assets.extractors.spine.models import BoneFollower, Spine, SpineInfo


class SetScaleTest(unittest.TestCase):
    def test_large_scale_divided_by_100(self):
        info = SpineInfo("a", "a")
        info.set_scale(300)
        self.assertEqual(3.0, info.scale)

    def test_normal_scale_kept(self):
        info = SpineInfo("a", "a")
        info.set_scale(1.5)
        self.assertEqual(1.5, info.scale)

    def test_boundary_scale_two_kept(self):
        info = SpineInfo("a", "a")
        info.set_scale(2)
        self.assertEqual(2, info.scale)


class SizeTest(unittest.TestCase):
    def test_found_size_takes_precedence(self):
        spine = Spine(name="s", found_size=(7, 8))
        spine.spines = [SpineInfo("a", "a", size=(100, 100))]
        self.assertEqual((7, 8), spine.size())

    def test_max_across_children(self):
        spine = Spine(name="s")
        spine.spines = [
            SpineInfo("a", "a", size=(10, 20)),
            SpineInfo("b", "b", size=(30, 5)),
        ]
        self.assertEqual((30, 20), spine.size())

    def test_none_when_no_sizes(self):
        spine = Spine(name="s")
        spine.spines = [SpineInfo("a", "a")]
        self.assertIsNone(spine.size())


class BoneFollowerTest(unittest.TestCase):
    def test_followers_wired_by_transform_id(self):
        spine = Spine(name="s")
        spine.spines = [SpineInfo("A", "a", transform_id=7)]
        spine.bone_followers = [
            BoneFollower(bone="bone", skeleton="skel", transforms={7}),
            BoneFollower(bone="bone2", skeleton="skel2", transforms={99}),
        ]
        spine.update_bone_followers()
        # Only the matching follower survives, wired to spine "A".
        self.assertEqual(1, len(spine.bone_followers))
        self.assertEqual({"A"}, spine.bone_followers[0].spines)


class FinalizeTest(unittest.TestCase):
    def test_sorts_by_order_without_order_list(self):
        spine = Spine(name="s")
        spine.spines = [
            SpineInfo("a", "a", order=2),
            SpineInfo("b", "b", order=1),
            SpineInfo("c", "c", order=3),
        ]
        spine.finalize()
        self.assertEqual(["b", "a", "c"], [s.name for s in spine.spines])

    def test_sorts_by_order_list_reversed(self):
        spine = Spine(name="s", spine_order_list=["10", "20"])
        s1 = SpineInfo("first", "first", ids={10})
        s2 = SpineInfo("second", "second", ids={20})
        spine.spines = [s1, s2]
        spine.finalize()
        # reverse=True on index lookup -> higher index first.
        self.assertEqual(["second", "first"], [s.name for s in spine.spines])


class FixActorSpineTest(unittest.TestCase):
    def test_generic_zeroes_position(self):
        spine = Spine(name="someactor", spine_order_list=["a", "b"])
        spine.spines = [SpineInfo("a", "a", position=(5, 5), scale=3)]
        spine.fix_actor_spine()
        info = spine.spines[0]
        self.assertEqual((0, 0), info.position)
        self.assertEqual(1, info.scale)
        self.assertEqual((0.5, 0), info.pivot)

    def test_biankaskin_reverses_list_and_keeps_position(self):
        spine = Spine(name="uimoviebiankaskin", spine_order_list=["a", "b"])
        spine.spines = [SpineInfo("a", "a", position=(5, 5))]
        spine.fix_actor_spine()
        self.assertEqual(["b", "a"], spine.spine_order_list)
        self.assertEqual((5, 5), spine.spines[0].position)
        self.assertEqual((0.5, 0), spine.spines[0].pivot)


class ToJsonTest(unittest.TestCase):
    def test_default_animation_is_most_common(self):
        spine = Spine(name="s")
        spine.spines = [
            SpineInfo("a", "a", default_animation="idle"),
            SpineInfo("b", "b", default_animation="idle"),
            SpineInfo("c", "c", default_animation="walk"),
        ]
        self.assertEqual("idle", spine.to_json()["defaultAnimation"])


if __name__ == "__main__":
    unittest.main()
