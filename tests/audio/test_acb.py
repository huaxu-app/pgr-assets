import unittest
from pathlib import Path

from pgr_assets.audio.acb import ACB

FIXTURE = Path(__file__).parent / "fixtures" / "mo_modelm.acb"


class CommandSynthIndexTest(unittest.TestCase):
    """Unit tests for the TLV command-stream parser, using synthetic byte
    sequences (no fixture needed)."""

    def test_note_on_type_2_returns_index(self):
        # opcode 0x07d0, size 4, payload = (type=2, index=0) — the real shape
        # taken from the fixture's first track event.
        self.assertEqual(0, ACB._command_synth_index(bytes.fromhex("07d00400020000000000")))

    def test_note_on_returns_referenced_index(self):
        # type=2, index=3
        self.assertEqual(3, ACB._command_synth_index(bytes.fromhex("07d00400020003")))

    def test_skips_leading_command_then_finds_note_on(self):
        # opcode 0x0001 (size 0), then the note-on (type=2, index=5).
        self.assertEqual(5, ACB._command_synth_index(bytes.fromhex("00010007d00400020005")))

    def test_non_synth_reference_type_ignored(self):
        # type=1 is not the SynthTable reference -> no match.
        self.assertIsNone(ACB._command_synth_index(bytes.fromhex("07d00400010005")))

    def test_end_marker_stops_walk(self):
        self.assertIsNone(ACB._command_synth_index(bytes.fromhex("000000")))

    def test_empty_command(self):
        self.assertIsNone(ACB._command_synth_index(b""))


class FirstTrackIndexTest(unittest.TestCase):
    def test_none_when_no_tracks(self):
        self.assertIsNone(ACB._first_track_index(0, b"\x00\x07"))

    def test_reads_big_endian_first_index(self):
        self.assertEqual(7, ACB._first_track_index(1, b"\x00\x07\x00\x09"))


class AcbFixtureTest(unittest.TestCase):
    """End-to-end table navigation against a real (self-contained) ACB bank.

    mo_modelm is a 13-cue character SFX bank: every cue is a plain sequence
    (ReferenceType 3) mapping 1:1 to waveform id == cue index.
    """

    @classmethod
    def setUpClass(cls):
        cls.acb = ACB(FIXTURE.read_bytes())

    def test_cue_names_and_indices(self):
        tables = self.acb.payload[0]
        names = {e["CueName"][1]: e["CueIndex"][1] for e in tables["CueNameTable"]}
        self.assertEqual(13, len(names))
        self.assertEqual(0, names["mo_modelm_atk0101"])
        self.assertEqual(12, names["mo_modelm_dandao04"])

    def test_all_cues_are_sequences(self):
        tables = self.acb.payload[0]
        self.assertEqual(
            {3}, {e["ReferenceType"][1] for e in tables["CueTable"]}
        )

    def test_waveform_ids_resolve_one_to_one(self):
        for idx in range(13):
            self.assertEqual([idx], self.acb.get_waveform_ids_for_cue_idx(idx))


if __name__ == "__main__":
    unittest.main()
