import io
import logging
import os
import wave
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import lameenc
import numpy as np

from pgr_assets.audio.plan import CuePlan, Layer

logger = logging.getLogger("audio.render")


class EmptyWaveform(Exception):
    """An empty AWB slot used by a placeholder cue."""


def encode_mp3(wav_bytes: bytes) -> bytes:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        pcm = wf.readframes(wf.getnframes())
        enc = lameenc.Encoder()
        enc.set_vbr(4)  # vbr_mtrh
        enc.set_vbr_quality(2)
        enc.set_in_sample_rate(wf.getframerate())
        enc.set_channels(wf.getnchannels())
        enc.set_quality(2)  # encoder algorithm effort, independent of VBR target
        return enc.encode(pcm) + enc.flush()


@dataclass(frozen=True)
class AudioFormat:
    extension: str
    encode: Callable[[bytes], bytes]


def _passthrough(wav: bytes) -> bytes:
    return wav


WAV = AudioFormat(".wav", _passthrough)
MP3 = AudioFormat(".mp3", encode_mp3)


@dataclass(frozen=True)
class Pcm:
    rate: int
    samples: np.ndarray


def read_wav(data: bytes) -> Pcm:
    with wave.open(io.BytesIO(data), "rb") as handle:
        rate = handle.getframerate()
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        frames = handle.readframes(handle.getnframes())
    if width != 2:
        raise ValueError(f"unsupported sample width {width}")
    samples = np.frombuffer(frames, "<i2").astype(np.float32) / 32768.0
    return Pcm(rate, samples.reshape(-1, channels))


def write_wav(pcm: Pcm) -> bytes:
    data = np.clip(np.round(pcm.samples * 32768.0), -32768, 32767).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(pcm.samples.shape[1])
        handle.setsampwidth(2)
        handle.setframerate(pcm.rate)
        handle.writeframes(data.tobytes())
    return buffer.getvalue()


def resample(pcm: Pcm, rate: int) -> Pcm:
    if pcm.rate == rate:
        return pcm
    frames = pcm.samples.shape[0]
    target = max(1, round(frames * rate / pcm.rate))
    source_times = np.arange(frames) / pcm.rate
    target_times = np.arange(target) / rate
    channels = [
        np.interp(target_times, source_times, pcm.samples[:, c])
        for c in range(pcm.samples.shape[1])
    ]
    return Pcm(rate, np.stack(channels, axis=1).astype(np.float32))


def mix(parts: list[tuple[Pcm, Layer]]) -> tuple[Pcm, float]:
    rate = max(pcm.rate for pcm, _ in parts)
    channels = max(pcm.samples.shape[1] for pcm, _ in parts)
    placed: list[tuple[int, np.ndarray]] = []
    length = 0
    for pcm, layer in parts:
        samples = resample(pcm, rate).samples
        if samples.shape[1] != channels:
            if samples.shape[1] != 1:
                raise ValueError(
                    f"cannot mix {samples.shape[1]} into {channels} channels"
                )
            samples = np.repeat(samples, channels, axis=1)
        start = round(layer.delay_ms * rate / 1000)
        placed.append((start, samples * layer.gain))
        length = max(length, start + samples.shape[0])
    out = np.zeros((length, channels), np.float32)
    for start, samples in placed:
        out[start : start + samples.shape[0]] += samples
    peak = float(np.abs(out).max()) if out.size else 0.0
    scale = 1.0 if peak <= 1.0 else 1.0 / peak
    return Pcm(rate, out * scale), scale


class Renderer:
    """Cache decoded waveforms until their last planned use."""

    def __init__(self, decode: Callable[[int], bytes], uses: Mapping[int, int]) -> None:
        self._decode = decode
        self._remaining = dict(uses)
        self._cache: dict[int, bytes] = {}

    def _wav(self, index: int) -> bytes:
        data = self._cache.pop(index, None)
        if data is None:
            data = self._decode(index)
        self._remaining[index] = self._remaining.get(index, 1) - 1
        if self._remaining[index] > 0:
            self._cache[index] = data
        return data

    def render(self, layers: tuple[Layer, ...]) -> tuple[bytes, float]:
        """Pass through a single undelayed layer without re-encoding its PCM.

        The planner normalizes standalone gain to 1.0.
        """
        if len(layers) == 1 and layers[0].delay_ms == 0:
            return self._wav(layers[0].waveform), 1.0
        pcm, scale = mix([(read_wav(self._wav(l.waveform)), l) for l in layers])
        return write_wav(pcm), scale


def _write(path: str, data: bytes) -> None:
    # Replace old links before writing to avoid overwriting their targets.
    if os.path.islink(path):
        os.remove(path)
    with open(path, "wb") as handle:
        handle.write(data)


def _link(path: str, target: str) -> None:
    if os.path.lexists(path):
        os.remove(path)
    os.symlink(target, path)


def write_cue(
    renderer: Renderer, dirname: str, name: str, plan: CuePlan, fmt: AudioFormat
) -> list[str]:
    """Write cue files and links, returning successfully written variants."""
    written: set[str] = set()
    for rendition in plan.renditions:
        stem = name + rendition.suffix
        try:
            wav, scale = renderer.render(rendition.layers)
        except EmptyWaveform as error:
            if len(rendition.layers) > 1:
                logger.warning(f"Skipping {stem}, a layer is empty: {error!r}")
            else:
                logger.debug(f"Skipping {stem}: {error!r}")
            continue
        if scale < 1.0:
            logger.debug(f"{stem}: mix scaled by {scale:.3f} to avoid clipping")
        delay = min(layer.delay_ms for layer in rendition.layers)
        if delay > 0:
            logger.debug(f"{stem}: starts {delay} ms in")
        _write(os.path.join(dirname, stem + fmt.extension), fmt.encode(wav))
        written.add(rendition.suffix)
    for suffix, target in plan.links.items():
        if target not in written:
            logger.warning(f"{name}{target} was not written, no link for it")
            continue
        _link(
            os.path.join(dirname, name + suffix + fmt.extension),
            name + target + fmt.extension,
        )
        written.add(suffix)
    return [v for v in plan.variants if "." + v in written]
