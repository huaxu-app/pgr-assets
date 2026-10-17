import unittest

from pgr_assets.audio.cuegraph import Effects, Sequence, Synth, Track, Waveform
from pgr_assets.audio.plan import (
    PLAIN_KEPT,
    RANDOM_IN_MIX,
    Layer,
    Rendition,
    WaveInfo,
    plan_blocks,
    plan_cue,
)

PLAIN = Effects()
SHORT = WaveInfo(samples=44100, rate=44100, loops=False)
LONG_LOOP = WaveInfo(samples=44100 * 60, rate=44100, loops=True)
SHORT_LOOP = WaveInfo(samples=44100 * 5, rate=44100, loops=True)


def wav(index):
    return Synth(PLAIN, [Waveform(index)])


def track(target, condition=None, delay=0, gain=1.0, muted=False, **effects):
    return Track(condition, delay, muted, Effects(gain=gain, **effects), target)


def seq(kind, *tracks, gain=1.0):
    return Sequence(kind, Effects(gain=gain), list(tracks))


def waves(count, info=SHORT):
    return {i: info for i in range(count)}


def suffixes(plan):
    return [r.suffix for r in plan.renditions]


class PlanTest(unittest.TestCase):
    def test_switch_labels_cannot_share_an_output_filename(self):
        tree = seq(
            8,
            track(wav(0), condition=("Switch", "A")),
            track(wav(1), condition=("Switch", "a")),
        )
        with self.assertRaisesRegex(RuntimeError, "collid"):
            plan_cue(tree, waves(2))

    def test_plain_cue(self):
        plan = plan_cue(seq(0, track(wav(3))), waves(4))
        self.assertEqual([Rendition("", (Layer(3, 0, 1.0),))], plan.renditions)
        self.assertEqual(({}, []), (plan.links, plan.variants))

    def test_layer_gains_are_relative_and_root_gain_cancels(self):
        tree = seq(0, track(wav(0), gain=0.5), track(wav(1), delay=600, gain=0.25))
        plan = plan_cue(tree, waves(2))
        self.assertEqual(
            (Layer(0, 0, 1.0), Layer(1, 600, 0.5)), plan.renditions[0].layers
        )
        plan = plan_cue(seq(0, track(wav(1), delay=400), gain=2.0), waves(2))
        self.assertEqual((Layer(1, 0, 1.0),), plan.renditions[0].layers)

    def test_muted_tracks_drop_and_a_fully_muted_cue_plays_unmuted(self):
        plan = plan_cue(seq(0, track(wav(0)), track(wav(1), muted=True)), waves(2))
        self.assertEqual((Layer(0, 0, 1.0),), plan.renditions[0].layers)
        plan = plan_cue(seq(0, track(wav(2), muted=True)), waves(3))
        self.assertEqual([Rendition("", (Layer(2, 0, 1.0),))], plan.renditions)

    def test_muted_first_track_keeps_the_plain_waveform(self):
        plan = plan_cue(seq(0, track(wav(0), muted=True), track(wav(1))), waves(2))
        self.assertEqual([Rendition("", (Layer(0, 0, 1.0),))], plan.renditions)
        self.assertIn(PLAIN_KEPT, plan.losses)

    def test_random_inside_a_mix_takes_first_and_logs(self):
        tree = seq(0, track(wav(0)), track(seq(4, track(wav(1)), track(wav(2)))))
        plan = plan_cue(tree, waves(3))
        self.assertEqual(
            (Layer(0, 0, 1.0), Layer(1, 0, 1.0)), plan.renditions[0].layers
        )
        self.assertIn(RANDOM_IN_MIX, plan.losses)
        plan = plan_cue(seq(4, track(wav(5)), track(wav(6))), waves(7))
        self.assertEqual(
            ((Layer(5, 0, 1.0),), []), (plan.renditions[0].layers, plan.losses)
        )

    def test_switch_branches_link_coinciding_labels_and_point_plain_at_first_waveform(
        self,
    ):
        tree = seq(
            8,
            track(wav(0), condition=("MusicSwitch", "A")),
            track(wav(1), condition=("MusicSwitch", "B")),
            track(wav(0), condition=("MusicSwitch", "C")),
        )
        plan = plan_cue(tree, waves(2))
        self.assertEqual([".a", ".b"], suffixes(plan))
        self.assertEqual({".c": ".a", "": ".a"}, plan.links)
        self.assertEqual(["a", "b", "c"], plan.variants)

    def test_step_switch_falls_back_to_road_and_keeps_shared_layers(self):
        tree = seq(
            0,
            track(seq(4, track(wav(0)), track(wav(1)))),
            track(wav(2), condition=("Step", "grass")),
            track(wav(3), condition=("Step", "road")),
        )
        plan = plan_cue(tree, waves(4))
        by_suffix = {r.suffix: r.layers for r in plan.renditions}
        self.assertEqual((Layer(0, 0, 1.0), Layer(3, 0, 1.0)), by_suffix[".road"])
        self.assertEqual((Layer(0, 0, 1.0), Layer(2, 0, 1.0)), by_suffix[".grass"])
        self.assertEqual(".road", plan.links[""])

    def test_labels_that_all_coincide_make_a_plain_cue(self):
        tree = seq(
            0,
            track(wav(4), condition=("1P3P", "1P")),
            track(wav(4), condition=("1P3P", "3P"), gain=0.6),
        )
        plan = plan_cue(tree, waves(5))
        self.assertEqual([""], suffixes(plan))
        self.assertEqual(({}, []), (plan.links, plan.variants))

    def test_switch_keeps_plain_waveform_when_no_branch_has_it(self):
        tree = seq(
            0,
            track(wav(0), muted=True),
            track(wav(1), condition=("VergilVoice", "Human")),
            track(wav(2), condition=("VergilVoice", "Devil")),
        )
        plan = plan_cue(tree, waves(3))
        self.assertEqual([".human", ".devil", ""], suffixes(plan))
        self.assertEqual({}, plan.links)
        self.assertIn(PLAIN_KEPT, plan.losses)

    def test_game_volume_stems_are_numbered_and_keep_delay(self):
        tree = seq(
            0,
            track(wav(0)),
            track(wav(1), game_volume=True),
            track(wav(2), delay=26319),
        )
        plan = plan_cue(tree, waves(3))
        self.assertEqual([".1", ".2", ".3"], suffixes(plan))
        self.assertEqual((Layer(2, 26319, 1.0),), plan.renditions[2].layers)
        self.assertEqual({"": ".1"}, plan.links)
        self.assertEqual(["1", "2", "3"], plan.variants)

    def test_song_lists_and_long_random_loops_split_but_short_loops_do_not(self):
        two = seq(1, track(wav(0)), track(wav(1)))
        self.assertEqual([".1", ".2"], suffixes(plan_cue(two, waves(2))))
        random = seq(3, track(wav(0)), track(wav(1)))
        self.assertEqual([".1", ".2"], suffixes(plan_cue(random, waves(2, LONG_LOOP))))
        self.assertEqual([""], suffixes(plan_cue(random, waves(2, SHORT_LOOP))))

    def test_switch_wins_over_stems(self):
        tree = seq(
            0,
            track(wav(0), condition=("1P3P", "1P"), game_volume=True),
            track(wav(1), condition=("1P3P", "3P")),
        )
        self.assertEqual([".1p", ".3p"], suffixes(plan_cue(tree, waves(2))))

    def test_empty_cue_has_no_rendition(self):
        self.assertEqual([], plan_cue(seq(0), waves(0)).renditions)
        self.assertEqual([], plan_cue(None, waves(0)).renditions)

    def test_blocks_keep_first_waveform_per_segment(self):
        trees = [
            seq(0),
            seq(0, track(wav(3))),
            seq(0, track(wav(3))),
            seq(0, track(wav(5))),
        ]
        plan = plan_blocks(trees)
        self.assertEqual(["_0", "_1"], suffixes(plan))
        self.assertEqual([""], suffixes(plan_blocks(trees[:2])))
