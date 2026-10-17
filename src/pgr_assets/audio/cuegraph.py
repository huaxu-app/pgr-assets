import struct
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

NOTE_ONS = frozenset({0x07D0, 0x07D3})
DELAY = 0x07D1
VOLUME = 0x92
MUTE = 0x21
PITCH_OPS = frozenset({0x05, 0x08})
SELECTOR = 0x64

REF_WAVEFORM = 1
REF_SYNTH = 2
REF_SEQUENCE = 3
REF_BLOCK_SEQUENCE = 8
WAVEFORM_ITEMS = frozenset({1, 5, 7})

SEQ_POLYPHONIC = 0
SEQ_SONG_LIST = 1
SEQ_RANDOM_TYPES = frozenset({3, 4})
SEQ_LAYERED_TYPES = frozenset({SEQ_POLYPHONIC, 7, 8})

GAME_CONTROL = 1
TIME_CONTROL = 2
VOLUME_GRAPH = 1
MAX_DEPTH = 12


@dataclass(frozen=True)
class Waveform:
    index: int


@dataclass(frozen=True)
class Effects:
    gain: float = 1.0
    pitched: bool = False
    game_volume: bool = False
    time_volume: bool = False


@dataclass
class Synth:
    effects: Effects
    items: list["Node"]


@dataclass
class Track:
    condition: tuple[str, str] | None
    delay_ms: int
    muted: bool
    effects: Effects
    target: "Node | None"


@dataclass
class Sequence:
    type: int
    effects: Effects
    tracks: list[Track]


Node = Sequence | Synth | Waveform


def value(row: Mapping[str, Any], column: str) -> Any:
    return row[column][1]


def commands(data: bytes) -> Iterator[tuple[int, bytes]]:
    """Read uint16 opcode, uint8 size and payload until opcode zero."""
    pos = 0
    while pos + 3 <= len(data):
        opcode = struct.unpack(">H", data[pos : pos + 2])[0]
        size = data[pos + 2]
        if opcode == 0:
            return
        yield opcode, data[pos + 3 : pos + 3 + size]
        pos += 3 + size


def u16s(data: Any) -> list[int]:
    if not isinstance(data, bytes | bytearray):
        return []
    count = len(data) // 2
    return list(struct.unpack(f">{count}H", data[: count * 2]))


class CueWalker:
    def __init__(self, tables: Mapping[str, Any]) -> None:
        self._tables = tables
        self._strings = [
            str(value(r, "StringValue")) for r in self.rows("StringValueTable")
        ]
        self._sequences = self.rows("SequenceTable")
        self._tracks = self.rows("TrackTable")
        self._events = self.rows("TrackEventTable")
        self._synths = self.rows("SynthTable")
        self._waveforms = self.rows("WaveformTable")
        self._aisacs = self.rows("AisacTable")
        self._graphs = self.rows("GraphTable")
        self._block_sequences = self.rows("BlockSequenceTable")
        self._blocks = self.rows("BlockTable")
        self._commands = {
            kind: self.rows(f"{kind}CommandTable") for kind in ("Seq", "Track", "Synth")
        }

    def is_block(self, index: int) -> bool:
        row = self.rows("CueTable")[index]
        return value(row, "ReferenceType") == REF_BLOCK_SEQUENCE

    def cue(self, index: int) -> Sequence | None:
        row = self.rows("CueTable")[index]
        if value(row, "ReferenceType") != REF_SEQUENCE:
            return None
        return self._sequence(value(row, "ReferenceIndex"), 0)

    def blocks(self, index: int) -> list[Sequence]:
        """Return the control tracks followed by each block's tracks."""
        row = self.rows("CueTable")[index]
        ref = value(row, "ReferenceIndex")
        if not self.is_block(index) or ref >= len(self._block_sequences):
            return []
        head = self._block_sequences[ref]
        count = value(head, "NumBlocks")
        block_rows = [
            self._blocks[b]
            for b in u16s(value(head, "BlockIndex"))[:count]
            if b < len(self._blocks)
        ]
        return [
            Sequence(SEQ_POLYPHONIC, Effects(), self._track_list(row, 0))
            for row in [head, *block_rows]
        ]

    def _track_list(self, row: Mapping[str, Any], depth: int) -> list[Track]:
        count = value(row, "NumTracks")
        indices = u16s(value(row, "TrackIndex"))[:count]
        return [self._track(t, depth) for t in indices if t < len(self._tracks)]

    def rows(self, name: str) -> list[Mapping[str, Any]]:
        """Return rows, treating unexpanded empty-table byte tuples as empty."""
        table = self._tables.get(name)
        return table if isinstance(table, list) else []

    def _string(self, index: int) -> str:
        return self._strings[index] if index < len(self._strings) else ""

    def _command_list(
        self, kind: str, row: Mapping[str, Any]
    ) -> list[tuple[int, bytes]]:
        table = self._commands[kind]
        index = value(row, "CommandIndex")
        if index is None or index >= len(table):
            return []
        return list(commands(value(table[index], "Command")))

    def _effects(
        self, row: Mapping[str, Any], found: list[tuple[int, bytes]]
    ) -> Effects:
        gain, pitched = 1.0, False
        for opcode, payload in found:
            if opcode == VOLUME and len(payload) >= 4:
                gain *= struct.unpack(">f", payload[:4])[0]
            elif opcode in PITCH_OPS and len(payload) >= 2:
                pitched = pitched or struct.unpack(">h", payload[:2])[0] != 0
        game_volume = time_volume = False
        for aisac in u16s(value(row, "LocalAisacs")):
            if aisac >= len(self._aisacs):
                continue
            entry = self._aisacs[aisac]
            # Older AISAC layouts omit ControlType.
            control = entry["ControlType"][1] if "ControlType" in entry else None
            graphs = u16s(entry["GraphIndexes"][1] if "GraphIndexes" in entry else b"")
            volume = any(
                g < len(self._graphs) and value(self._graphs[g], "Type") == VOLUME_GRAPH
                for g in graphs
            )
            game_volume = game_volume or (volume and control == GAME_CONTROL)
            time_volume = time_volume or (volume and control == TIME_CONTROL)
        return Effects(gain, pitched, game_volume, time_volume)

    def _reference(self, kind: int, index: int, depth: int) -> Node | None:
        if kind == REF_WAVEFORM and index < len(self._waveforms):
            return Waveform(index)
        if kind == REF_SYNTH and index < len(self._synths) and depth < MAX_DEPTH:
            return self._synth(index, depth + 1)
        if kind == REF_SEQUENCE and index < len(self._sequences) and depth < MAX_DEPTH:
            return self._sequence(index, depth + 1)
        return None

    def _synth(self, index: int, depth: int) -> Synth:
        row = self._synths[index]
        items = u16s(value(row, "ReferenceItems"))
        nodes: list[Node] = []
        for kind, ref in zip(items[::2], items[1::2]):
            node = self._reference(
                REF_WAVEFORM if kind in WAVEFORM_ITEMS else kind, ref, depth
            )
            if node is not None:
                nodes.append(node)
        return Synth(self._effects(row, self._command_list("Synth", row)), nodes)

    def _sequence(self, index: int, depth: int) -> Sequence:
        row = self._sequences[index]
        return Sequence(
            value(row, "Type"),
            self._effects(row, self._command_list("Seq", row)),
            self._track_list(row, depth),
        )

    def _track(self, index: int, depth: int) -> Track:
        """Resolve note-ons with cumulative event delays.

        Multiple notes become a layered sequence under the track.
        """
        row = self._tracks[index]
        found = self._command_list("Track", row)
        condition, muted = None, False
        for opcode, payload in found:
            if opcode == SELECTOR and len(payload) >= 4:
                selector, label = struct.unpack(">HH", payload[:4])
                condition = (self._string(selector), self._string(label))
            elif opcode == MUTE and payload[:1] == b"\x01":
                muted = True
        effects = self._effects(row, found)
        notes: list[Track] = []
        delay_ms = 0
        event = value(row, "EventIndex")
        if event is not None and event < len(self._events):
            for opcode, payload in commands(value(self._events[event], "Command")):
                if len(payload) < 4:
                    continue
                if opcode == DELAY:
                    delay_ms += struct.unpack(">I", payload[:4])[0]
                elif opcode in NOTE_ONS:
                    kind, ref = struct.unpack(">HH", payload[:4])
                    target = self._reference(kind, ref, depth)
                    notes.append(Track(None, delay_ms, False, Effects(), target))
        if not notes:
            return Track(condition, 0, muted, effects, None)
        if len(notes) == 1:
            return Track(condition, notes[0].delay_ms, muted, effects, notes[0].target)
        return Track(
            condition, 0, muted, effects, Sequence(SEQ_POLYPHONIC, Effects(), notes)
        )
