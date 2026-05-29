# Heavily modified PyCriCodecs.ACBj
import logging
import os
import struct
from typing import cast, Any, List

from PyCriCodecs import UTF, AWB, UTFTypeValues, UTFType, HCA
from ffmpeg import FFmpeg

logger = logging.getLogger("audio.acb")


class ACB:
    """An ACB is basically a giant @UTF table. Use this class to extract any ACB."""

    __slots__ = ["payload", "awb"]
    payload: list
    awb: AWB

    def __init__(self, acb, awb: bytes | str = b"") -> None:
        self.payload = UTF(acb).get_payload()
        self.acb_parse(self.payload)
        if awb:
            self.awb = AWB(awb)
        else:
            self.awb = AWB(self.payload[0]["AwbFile"][1])

    def acb_parse(self, payload: list) -> None:
        """Recursively parse the payload."""
        for items in range(len(payload)):
            for k, v in payload[items].items():
                if v[0] == UTFTypeValues.bytes:
                    if v[
                        1
                    ].startswith(
                        UTFType.UTF.value
                    ):  # or v[1].startswith(UTFType.EUTF.value): # ACB's never gets encrypted?
                        par = UTF(v[1]).get_payload()
                        payload[items][k] = par
                        self.acb_parse(par)

    @staticmethod
    def _first_track_index(num_tracks: int, track_index_bytes: bytes) -> int | None:
        if num_tracks == 0:
            return None
        return struct.unpack(">H", track_index_bytes[:2])[0]

    @staticmethod
    def _command_synth_index(command: bytes) -> int | None:
        """Walk the TLV command stream and return the referenced synth index.

        Commands are a series of (uint16 opcode, uint8 size, payload[size]) tuples.
        The note-on command (opcode 0x07d0) carries a (uint16 type, uint16 index)
        reference; type 0x02 means it points at the SynthTable.
        """
        pos = 0
        while pos + 3 <= len(command):
            opcode = struct.unpack(">H", command[pos : pos + 2])[0]
            size = command[pos + 2]
            if opcode == 0:  # end-of-command marker
                break
            if opcode == 0x07D0 and size >= 4:
                ref_type, ref_index = struct.unpack(">HH", command[pos + 3 : pos + 7])
                if ref_type == 2:
                    return ref_index
            pos += 3 + size
        return None

    def _track_waveform_id(self, track_index: int) -> int | None:
        track = self.payload[0]["TrackTable"][track_index]
        event_index = track["EventIndex"][1]
        track_event_table = self.payload[0]["TrackEventTable"]
        if event_index >= len(track_event_table):  # 0xFFFF == no event (empty track)
            return None

        command = track_event_table[event_index]["Command"][1]
        synth_index = self._command_synth_index(command)
        if synth_index is None:
            return None

        synth_reference_items = self.payload[0]["SynthTable"][synth_index][
            "ReferenceItems"
        ][1]
        waveform_index = struct.unpack(">H", synth_reference_items[2:4])[0]

        waveform = self.payload[0]["WaveformTable"][waveform_index]
        if waveform["Streaming"][1] > 0:
            return waveform["StreamAwbId"][1]
        return waveform["MemoryAwbId"][1]

    def _sequence_track_indices(self, sequence_index: int) -> list[int]:
        sequence = self.payload[0]["SequenceTable"][sequence_index]
        first = self._first_track_index(
            sequence["NumTracks"][1], sequence["TrackIndex"][1]
        )
        return [first] if first is not None else []

    def _block_sequence_track_indices(self, block_sequence_index: int) -> list[int]:
        block_sequence = self.payload[0]["BlockSequenceTable"][block_sequence_index]
        track_indices: list[int] = []

        # The block sequence's own track (usually an empty control track).
        own = self._first_track_index(
            block_sequence["NumTracks"][1], block_sequence["TrackIndex"][1]
        )
        if own is not None:
            track_indices.append(own)

        # Each block is a sequential segment with its own waveform.
        num_blocks = block_sequence["NumBlocks"][1]
        block_indices = struct.unpack(
            f">{num_blocks}H", block_sequence["BlockIndex"][1][: num_blocks * 2]
        )
        for block_index in block_indices:
            block = self.payload[0]["BlockTable"][block_index]
            first = self._first_track_index(
                block["NumTracks"][1], block["TrackIndex"][1]
            )
            if first is not None:
                track_indices.append(first)

        return track_indices

    def get_waveform_ids_for_cue_idx(self, idx: int) -> list[int]:
        cue_entry = self.payload[0]["CueTable"][idx]
        reference_index = cue_entry["ReferenceIndex"][1]
        reference_type = cue_entry["ReferenceType"][1]

        if reference_type == 3:
            track_indices = self._sequence_track_indices(reference_index)
        elif reference_type == 8:
            track_indices = self._block_sequence_track_indices(reference_index)
        else:
            raise RuntimeError(
                f"Reference type {reference_type} not supported for cue {idx}"
            )

        waveform_ids: list[int] = []
        for track_index in track_indices:
            waveform_id = self._track_waveform_id(track_index)
            if waveform_id is not None and waveform_id not in waveform_ids:
                waveform_ids.append(waveform_id)
        return waveform_ids

    def extract(self, key: int, dirname: str = "", encode=False):
        """Extracts audio files in an AWB/ACB without preserving filenames."""
        if dirname:
            os.makedirs(dirname, exist_ok=True)

        # Have to do this because the index one is broken
        waveforms: List[Any] = list(self.awb.getfiles())

        tables = self.payload[0]

        for cue_name_entry in tables["CueNameTable"]:
            cue_name = str(cue_name_entry["CueName"][1]).lower()
            cue_idx = cue_name_entry["CueIndex"][1]
            try:
                waveform_ids = self.get_waveform_ids_for_cue_idx(cue_idx)
            except IndexError:
                logger.warning(f"Failed to resolve waveforms for cue {cue_name}")
                continue

            # A block sequence yields one waveform per segment; suffix them so
            # they don't overwrite each other. A plain cue keeps its bare name.
            for n, waveform_id in enumerate(waveform_ids):
                name = cue_name if len(waveform_ids) == 1 else f"{cue_name}_{n}"
                try:
                    data = waveforms[waveform_id]
                    if not data:  # placeholder cue with no audio (empty AWB slot)
                        logger.debug(f"Skipping empty waveform for cue {name}")
                        continue
                    audio = HCA(
                        data, key=key, subkey=cast(Any, self.awb.subkey)
                    ).decode()

                    if encode:
                        ffmpeg = (
                            FFmpeg()
                            .option("y")
                            .option("hwaccel", "auto")
                            .input("pipe:0")
                            .output(
                                os.path.join(dirname, name + ".mp3"),
                                {"c:a": "libmp3lame", "q:a": 2},
                            )
                        )

                        ffmpeg.execute(audio)
                    else:
                        with open(os.path.join(dirname, name + ".wav"), "wb") as f:
                            f.write(audio)
                except IndexError:
                    logger.warning(
                        f"Failed to extract {name} with index {cue_idx}: waveform index out of range"
                    )
