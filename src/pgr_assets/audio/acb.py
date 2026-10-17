# Heavily modified PyCriCodecs.ACB
import logging
import os
from typing import Any, cast

from pgr_assets.audio.cuegraph import CueWalker, value
from pgr_assets.audio.paths import cue_stem
from pgr_assets.audio.plan import CuePlan, WaveInfo, plan_blocks, plan_cue
from pgr_assets.audio.render import (
    WAV,
    AudioFormat,
    EmptyWaveform,
    Renderer,
    write_cue,
)
from pgr_assets.cri import AWB, HCA, UTF, UTFType, UTFTypeValues

logger = logging.getLogger("audio.acb")


def _is_awb(awb: bytes) -> bool:
    return awb[:4] == b"AFS2"


class ACB:
    """Parse nested ACB tables and extract named audio cues."""

    __slots__ = ["awb", "payload"]
    payload: list
    awb: AWB | None

    def __init__(self, acb, awb: bytes = b"") -> None:
        self.payload = UTF(acb).get_payload()
        self.acb_parse(self.payload)
        # AWB wraps bytes in BytesIO despite its BinaryIO annotation.
        if not awb:
            awb = self.payload[0]["AwbFile"][1]
        self.awb = AWB(cast(Any, awb)) if _is_awb(awb) else None

    def acb_parse(self, payload: list) -> None:
        """Expand nested UTF tables in place."""
        for items in range(len(payload)):
            for k, v in payload[items].items():
                if v[0] == UTFTypeValues.bytes and v[1].startswith(UTFType.UTF.value):
                    par = UTF(v[1]).get_payload()
                    payload[items][k] = par
                    self.acb_parse(par)

    def _awb_id(self, waveform_index: int) -> int:
        waveform = self.payload[0]["WaveformTable"][waveform_index]
        if value(waveform, "Streaming") > 0:
            return value(waveform, "StreamAwbId")
        return value(waveform, "MemoryAwbId")

    def plans(self) -> dict[str, CuePlan]:
        """Plan named cues and reject output filename collisions."""
        walker = CueWalker(self.payload[0])
        waves = {
            index: WaveInfo(
                value(row, "NumSamples"),
                value(row, "SamplingRate"),
                value(row, "LoopFlag") == 2,
            )
            for index, row in enumerate(walker.rows("WaveformTable"))
        }
        names: dict[str, int] = {}
        for entry in walker.rows("CueNameTable"):
            name = cue_stem(str(value(entry, "CueName")))
            if name in names:
                raise RuntimeError(f"{name} collides with a cue name")
            names[name] = value(entry, "CueIndex")
        plans: dict[str, CuePlan] = {}
        output_names = set(names)
        for name, cue_index in names.items():
            if walker.is_block(cue_index):
                plan = plan_blocks(walker.blocks(cue_index))
            else:
                plan = plan_cue(walker.cue(cue_index), waves)
            for loss in plan.losses:
                logger.warning(f"{name}: {loss}")
            for suffix in [r.suffix for r in plan.renditions] + list(plan.links):
                if not suffix:
                    continue
                stem = name + suffix
                if stem in output_names:
                    raise RuntimeError(f"{stem} collides with another output name")
                output_names.add(stem)
            plans[name] = plan
        return plans

    def extract(
        self, key: int, dirname: str = "", fmt: AudioFormat = WAV
    ) -> dict[str, list[str]]:
        """Write playable cues, switch branches and music parts.

        Return variant suffixes for cues with successfully written variants.
        """
        awb = self.awb
        if awb is None:
            logger.debug("ACB has no AWB, nothing to extract")
            return {}
        if dirname:
            os.makedirs(dirname, exist_ok=True)

        plans = self.plans()
        waveforms: list[Any] = list(awb.getfiles())
        # AWB annotates subkey as bytes, but its header unpacks an int.
        subkey = cast(int, awb.subkey)

        def decode(index: int) -> bytes:
            awb_id = self._awb_id(index)
            data = waveforms[awb_id] if awb_id < len(waveforms) else b""
            if not data:
                raise EmptyWaveform(index)
            return HCA(data, key=key, subkey=subkey).decode()

        uses: dict[int, int] = {}
        for plan in plans.values():
            for rendition in plan.renditions:
                for layer in rendition.layers:
                    uses[layer.waveform] = uses.get(layer.waveform, 0) + 1
        renderer = Renderer(decode, uses)

        variants: dict[str, list[str]] = {}
        for name, plan in plans.items():
            done = write_cue(renderer, dirname, name, plan, fmt)
            if done:
                variants[name] = done
        return variants
