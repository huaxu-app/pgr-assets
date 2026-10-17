import unittest
from io import BytesIO
from types import SimpleNamespace

import numpy as np
from PIL import Image

from pgr_assets.models.faces import FACE_SLOT
from pgr_assets.models.texture import (
    WEBP_LOSSLESS,
    TextureSet,
    decode_ag_normal,
)


def image(pixels) -> Image.Image:
    return Image.fromarray(np.asarray(pixels, np.uint8), "RGBA")


def texture(path_id: int, pixels, wrap_u=0, wrap_v=0, filter_mode=1):
    asset = SimpleNamespace(
        m_Name=f"tex{path_id}",
        image=image(pixels),
        m_TextureFormat=SimpleNamespace(name="DXT5"),
        m_ColorSpace=1,
        m_TextureSettings=SimpleNamespace(
            m_WrapU=wrap_u, m_WrapV=wrap_v, m_FilterMode=filter_mode
        ),
        object_reader=SimpleNamespace(
            assets_file=SimpleNamespace(name="CAB-abc"), path_id=path_id
        ),
    )
    return SimpleNamespace(m_PathID=path_id, read=lambda: asset)


def signed(channel: np.ndarray) -> np.ndarray:
    return channel.astype(np.float64) / 255.0 * 2.0 - 1.0


class NormalDecodeTest(unittest.TestCase):
    def test_a_flat_ag_normal_decodes_to_straight_out(self):
        decoded = np.asarray(decode_ag_normal(image([[[255, 128, 128, 128]]])))
        self.assertTrue(np.array_equal([128, 128, 255], decoded[0, 0]))

    def test_the_decoded_normal_is_a_unit_vector(self):
        packed = [
            [[255, g, g, a] for a in range(40, 216, 25)] for g in range(40, 216, 25)
        ]
        decoded = np.asarray(decode_ag_normal(image(packed))).astype(np.float64)
        lengths = np.linalg.norm(
            np.stack([signed(decoded[..., i]) for i in range(3)], axis=-1), axis=-1
        )
        self.assertTrue(np.allclose(lengths, 1.0, atol=0.02))


class EncodingPolicyTest(unittest.TestCase):
    def set_with(self, *bindings) -> TextureSet:
        textures = TextureSet()
        for path_id, slot in bindings:
            textures.add(texture(path_id, [[[10, 20, 30, 255]]]), slot, "part")
        textures.finish(set(textures.textures))
        return textures

    def one(self, *bindings):
        return next(iter(self.set_with(*bindings).textures.values()))

    def test_a_color_slot_encodes_lossy(self):
        self.assertFalse(self.one((1, "_MainTex")).lossless)

    def test_a_packed_data_slot_encodes_lossless(self):
        self.assertTrue(self.one((1, "_MaskTex")).lossless)

    def test_an_unknown_slot_fails_closed(self):
        self.assertTrue(self.one((1, "_SomeFutureMap")).lossless)

    def test_two_slots_fall_back_to_lossless(self):
        self.assertTrue(self.one((1, "_MainTex"), (1, "_MaskTex")).lossless)

    def test_a_bump_slot_is_decoded_and_encodes_lossy(self):
        entry = self.one((1, "_BumpMap"))
        self.assertTrue(entry.normal)
        self.assertFalse(entry.lossless)

    def test_webp_lossless_keeps_every_slot_lossless(self):
        for slot in ("_MainTex", "_BumpMap"):
            textures = TextureSet(WEBP_LOSSLESS)
            textures.add(texture(1, [[[10, 20, 30, 255]]]), slot, "part")
            textures.finish(set(textures.textures))
            self.assertTrue(next(iter(textures.textures.values())).lossless)

    def test_a_lossless_packed_channel_round_trips_exactly(self):
        packed = np.random.default_rng(0).integers(0, 256, (16, 16, 4), dtype=np.uint8)
        textures = TextureSet()
        textures.add(texture(1, packed), "_MaskTex", "part")
        textures.finish(set(textures.textures))
        entry = next(iter(textures.textures.values()))
        decoded = np.asarray(Image.open(BytesIO(entry.webp)).convert("RGBA"))
        self.assertEqual(0, int(np.abs(decoded.astype(int) - packed.astype(int)).max()))

    def test_a_pending_face_slot_holds_back_what_it_could_flip(self):
        textures = TextureSet()
        main = textures.add(texture(1, [[[10, 20, 30, 255]]]), "_MainTex", "part")
        mask = textures.add(texture(2, [[[40, 50, 60, 255]]]), "_MaskTex", "part")
        bump = textures.add(texture(3, [[[70, 80, 90, 255]]]), "_BumpMap", "part")
        assert main is not None and mask is not None and bump is not None
        textures.encode({main, mask, bump}, FACE_SLOT)
        self.assertEqual(b"", textures.textures[main].webp)
        self.assertNotEqual(b"", textures.textures[mask].webp)
        self.assertNotEqual(b"", textures.textures[bump].webp)
        textures.add(texture(1, [[[10, 20, 30, 255]]]), FACE_SLOT, "face")
        textures.finish({main, mask, bump})
        self.assertTrue(textures.textures[main].lossless)


if __name__ == "__main__":
    unittest.main()
