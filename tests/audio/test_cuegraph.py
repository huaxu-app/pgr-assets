import struct
import unittest

from pgr_assets.audio.cuegraph import (
    MAX_DEPTH,
    CueWalker,
    Sequence,
    Synth,
    Waveform,
    commands,
)


def col(value):
    return (0, value)


def cmd(opcode, payload=b""):
    return struct.pack(">HB", opcode, len(payload)) + payload


def note_on(kind, index):
    return cmd(0x07D0, struct.pack(">HH", kind, index))


def delay(ms):
    return cmd(0x07D1, struct.pack(">I", ms))


def row(**columns):
    return {k: col(v) for k, v in columns.items()}


def sequence(kind, *tracks, command=0xFFFF):
    return row(
        Type=kind,
        NumTracks=len(tracks),
        TrackIndex=struct.pack(f">{len(tracks)}H", *tracks),
        CommandIndex=command,
        LocalAisacs=b"",
    )


def track(event, command=0xFFFF, aisacs=b""):
    return row(EventIndex=event, CommandIndex=command, LocalAisacs=aisacs)


def synth(*items, command=0xFFFF):
    return row(
        Type=0,
        ReferenceItems=struct.pack(f">{len(items)}H", *items),
        CommandIndex=command,
        LocalAisacs=b"",
    )


def walker(**tables):
    base = {
        "CueTable": [row(ReferenceType=3, ReferenceIndex=0)],
        "WaveformTable": [row(NumSamples=1), row(NumSamples=1)],
        "StringValueTable": [row(StringValue="Step"), row(StringValue="road")],
    }
    return CueWalker(base | tables)


class CommandStreamTest(unittest.TestCase):
    def test_stops_at_zero_opcode_and_truncated_tail(self):
        data = cmd(0x21, b"\x01") + cmd(0) + note_on(1, 0)
        self.assertEqual([(0x21, b"\x01")], list(commands(data)))
        self.assertEqual([], list(commands(b"\x07\xd0")))


class CueWalkerTest(unittest.TestCase):
    def test_track_condition_gain_delay_and_synth_target(self):
        w = walker(
            SequenceTable=[sequence(0, 0, 1)],
            TrackTable=[track(0, command=0), track(1)],
            TrackEventTable=[
                row(Command=note_on(2, 0)),
                row(Command=delay(250) + note_on(2, 1)),
            ],
            TrackCommandTable=[
                row(
                    Command=cmd(0x64, struct.pack(">HH", 0, 1))
                    + cmd(0x92, struct.pack(">f", 0.5))
                )
            ],
            SynthTable=[synth(1, 0), synth(1, 1)],
        )
        tree = w.cue(0)
        assert isinstance(tree, Sequence)
        first, second = tree.tracks
        self.assertEqual(("Step", "road"), first.condition)
        self.assertEqual(0.5, first.effects.gain)
        assert isinstance(first.target, Synth)
        self.assertEqual(Waveform(0), first.target.items[0])
        self.assertEqual((None, 250), (second.condition, second.delay_ms))

    def test_several_note_ons_become_a_layered_sequence(self):
        w = walker(
            SequenceTable=[sequence(0, 0)],
            TrackTable=[track(0, command=0)],
            TrackEventTable=[
                row(Command=delay(100) + note_on(1, 0) + delay(50) + note_on(1, 1))
            ],
            TrackCommandTable=[row(Command=cmd(0x21, b"\x01"))],
        )
        tree = w.cue(0)
        assert tree is not None
        (outer,) = tree.tracks
        self.assertTrue(outer.muted)
        assert isinstance(outer.target, Sequence)
        first, second = outer.target.tracks
        self.assertEqual((100, Waveform(0)), (first.delay_ms, first.target))
        self.assertEqual((150, Waveform(1)), (second.delay_ms, second.target))

    def test_alternate_note_on_opcode(self):
        w = walker(
            SequenceTable=[sequence(0, 0)],
            TrackTable=[track(0)],
            TrackEventTable=[
                row(Command=bytes.fromhex("07c70600000bb8000007d306000100000000"))
            ],
        )
        tree = w.cue(0)
        assert tree is not None
        self.assertEqual(Waveform(0), tree.tracks[0].target)

    def test_aisac_volume_graphs_set_control_flags(self):
        w = walker(
            SequenceTable=[sequence(0, 0, 1)],
            TrackTable=[
                track(0, aisacs=struct.pack(">H", 0)),
                track(0, aisacs=struct.pack(">H", 1)),
            ],
            TrackEventTable=[row(Command=note_on(1, 0))],
            AisacTable=[
                row(ControlType=1, GraphIndexes=struct.pack(">H", 0)),
                row(ControlType=2, GraphIndexes=struct.pack(">H", 0)),
            ],
            GraphTable=[row(Type=1)],
        )
        tree = w.cue(0)
        assert tree is not None
        game, time = (t.effects for t in tree.tracks)
        self.assertEqual((True, False), (game.game_volume, game.time_volume))
        self.assertEqual((False, True), (time.game_volume, time.time_volume))

    def test_self_reference_stops_at_depth_bound(self):
        w = walker(
            SequenceTable=[sequence(0, 0)],
            TrackTable=[track(0)],
            TrackEventTable=[row(Command=note_on(3, 0))],
        )
        node = w.cue(0)
        depth = 0
        while isinstance(node, Sequence):
            node = node.tracks[0].target
            depth += 1
        self.assertIsNone(node)
        self.assertEqual(MAX_DEPTH + 1, depth)

    def test_block_sequence_yields_control_track_then_segments(self):
        w = walker(
            CueTable=[row(ReferenceType=8, ReferenceIndex=0)],
            BlockSequenceTable=[
                row(NumTracks=0, TrackIndex=b"", NumBlocks=2, BlockIndex=b"\0\0\0\1")
            ],
            BlockTable=[
                row(NumTracks=1, TrackIndex=b"\0\0"),
                row(NumTracks=1, TrackIndex=b"\0\1"),
            ],
            TrackTable=[track(0), track(1)],
            TrackEventTable=[row(Command=note_on(1, 0)), row(Command=note_on(1, 1))],
        )
        self.assertIsNone(w.cue(0))
        head, first, second = w.blocks(0)
        self.assertEqual([], head.tracks)
        self.assertEqual(Waveform(0), first.tracks[0].target)
        self.assertEqual(Waveform(1), second.tracks[0].target)
