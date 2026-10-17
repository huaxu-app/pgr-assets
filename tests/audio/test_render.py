import pickle
import unittest

import numpy as np

from pgr_assets.audio.plan import Layer
from pgr_assets.audio.render import (
    WAV,
    Pcm,
    Renderer,
    mix,
    read_wav,
    resample,
    write_wav,
)


def tone(rate, frames, channels, level):
    return Pcm(rate, np.full((frames, channels), level, np.float32))


class RenderTest(unittest.TestCase):
    def test_wav_format_survives_worker_serialization(self):
        fmt = pickle.loads(pickle.dumps(WAV))
        raw = write_wav(tone(1000, 2, 1, 0.1))
        self.assertEqual(".wav", fmt.extension)
        self.assertEqual(raw, fmt.encode(raw))

    def test_wav_roundtrip_is_exact(self):
        values = np.array([[32767], [-32768], [20000], [16383]], np.int16)
        pcm = Pcm(44100, values.astype(np.float32) / 32768.0)
        back = read_wav(write_wav(pcm))
        self.assertEqual(44100, back.rate)
        restored = np.round(back.samples * 32768.0).astype(np.int16)
        np.testing.assert_array_equal(values, restored)

    def test_mix_applies_delay_gain_and_mono_to_stereo(self):
        out, scale = mix(
            [
                (tone(1000, 4, 2, 0.2), Layer(0, 0, 1.0)),
                (tone(1000, 2, 1, 0.4), Layer(1, 2, 0.5)),
            ]
        )
        self.assertEqual(1.0, scale)
        self.assertEqual((4, 2), out.samples.shape)
        self.assertAlmostEqual(0.2, float(out.samples[1, 1]), places=5)
        self.assertAlmostEqual(0.4, float(out.samples[2, 0]), places=5)

    def test_mix_scales_down_only_past_full_scale(self):
        loud = tone(1000, 2, 1, 0.8)
        out, scale = mix([(loud, Layer(0, 0, 1.0)), (loud, Layer(0, 0, 1.0))])
        self.assertAlmostEqual(1 / 1.6, scale, places=5)
        self.assertAlmostEqual(1.0, float(np.abs(out.samples).max()), places=5)

    def test_mix_resamples_to_the_highest_rate(self):
        low, high = tone(44100, 441, 1, 0.1), tone(48000, 480, 1, 0.1)
        out, _ = mix([(low, Layer(0, 0, 1.0)), (high, Layer(1, 0, 1.0))])
        self.assertEqual(48000, out.rate)
        self.assertEqual(480, resample(low, 48000).samples.shape[0])

    def test_single_layer_is_passed_through_untouched(self):
        raw = write_wav(tone(44100, 3, 1, 0.25))
        renderer = Renderer(lambda index: raw, {7: 1})
        data, scale = renderer.render((Layer(7, 0, 0.3),))
        self.assertEqual(raw, data)
        self.assertEqual(1.0, scale)

    def test_decode_is_cached_until_last_use(self):
        calls = []
        raw = write_wav(tone(1000, 2, 1, 0.1))

        def decode(index):
            calls.append(index)
            return raw

        renderer = Renderer(decode, {1: 2})
        renderer.render((Layer(1, 0, 1.0),))
        renderer.render((Layer(1, 0, 1.0),))
        self.assertEqual([1], calls)
