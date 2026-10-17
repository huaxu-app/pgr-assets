import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import numpy as np
from PIL import Image

from pgr_assets.models.unity import read_pointer, resolve_asset_key

logger = logging.getLogger("pgr-assets")

ENCODE_WORKERS = 4
LOSSY_QUALITY = 90
ENCODE_METHOD = 0

BUMP_SLOT = "_BumpMap"
EYE_MASK_SLOT = "_EyeMask"
LOSSY_SLOTS = frozenset({"_MainTex", "_MatCapTex", "_DetailMap", "_SecondTex", BUMP_SLOT})

# glTF samplers take raw GL enum values.
REPEAT, CLAMP_TO_EDGE, MIRRORED_REPEAT = 10497, 33071, 33648
NEAREST, LINEAR = 9728, 9729

# Unity TextureWrapMode. MirrorOnce is 3 and has no glTF equivalent.
WRAP_MODES = {0: REPEAT, 1: CLAMP_TO_EDGE, 2: MIRRORED_REPEAT}
# Unity FilterMode. Bilinear and Trilinear both become LINEAR without mips.
POINT_FILTER = 0


def read_color_space(texture: Any) -> str:
    return "sRGB" if texture.m_ColorSpace else "linear"


def encode_webp(image: Image.Image, lossless: bool) -> bytes:
    buffer = BytesIO()
    # `exact` because alpha here is a data channel and not
    # transparency. Without it libwebp flattens the RGB when A=0.
    if lossless:
        image.save(buffer, "WEBP", lossless=True, exact=True, method=ENCODE_METHOD)
    else:
        image.save(
            buffer, "WEBP", quality=LOSSY_QUALITY, exact=True, method=ENCODE_METHOD
        )
    return buffer.getvalue()


@dataclass
class Texture:
    name: str
    color_space: str
    wrap_s: int
    wrap_t: int
    mag_filter: int
    lossless: bool = True
    normal: bool = False
    webp: bytes = b""


@dataclass(frozen=True)
class TextureEncoding:
    name: str
    # Slots that may go lossy. A texture bound by any second slot stays lossless.
    lossy_slots: frozenset[str]

    def is_lossless(self, slots: set[str]) -> bool:
        return not (len(slots) == 1 and slots <= self.lossy_slots)


WEBP = TextureEncoding("webp", LOSSY_SLOTS)
WEBP_LOSSLESS = TextureEncoding("webp-lossless", frozenset())
TEXTURE_ENCODINGS = {e.name: e for e in (WEBP, WEBP_LOSSLESS)}


class TextureSet:
    def __init__(self, encoding: TextureEncoding = WEBP) -> None:
        self.encoding = encoding
        self.textures: dict[str, Texture] = {}
        self._images: dict[str, Image.Image] = {}
        self._slots: dict[str, set[str]] = {}
        self._aliases: dict[str, str] = {}
        self._by_content: dict[tuple, str] = {}

    def add(self, pointer: Any, slot: str, where: str) -> str | None:
        """
        Register a texture binding and return its key, or None if it is unusable.
        """
        texture = read_pointer(pointer, where, f"{slot} texture pointer")
        if texture is None:
            return None

        key = resolve_asset_key(texture)
        if slot == BUMP_SLOT:
            key += ":normal"
        key = self._aliases.get(key, key)
        self._slots.setdefault(key, set()).add(slot)
        if key in self.textures:
            return key

        try:
            image = texture.image
        except Exception as error:  # noqa: BLE001  a bad decode costs one slot, not the part
            logger.warning(
                f"{where}: {slot} texture did not decode,"
                f" {type(error).__name__}: {error}"
            )
            self._slots.pop(key, None)
            return None

        settings = texture.m_TextureSettings
        entry = Texture(
            name=texture.m_Name,
            color_space=read_color_space(texture),
            wrap_s=_convert_wrap(settings.m_WrapU, where),
            wrap_t=_convert_wrap(settings.m_WrapV, where),
            mag_filter=NEAREST if settings.m_FilterMode == POINT_FILTER else LINEAR,
        )
        # Match pixels, sampling settings and normal-map decoding across bundles.
        content = (
            hashlib.sha1(image.tobytes()).digest(),
            image.mode,
            image.size,
            entry.color_space,
            entry.wrap_s,
            entry.wrap_t,
            entry.mag_filter,
            slot == BUMP_SLOT,
        )
        twin = self._by_content.get(content)
        if twin is not None:
            self._aliases[key] = twin
            self._slots[twin] |= self._slots.pop(key)
            return twin

        self._by_content[content] = key
        self.textures[key] = entry
        self._images[key] = image
        return key

    def encode(self, keys: set[str], pending: str | None) -> None:
        """
        Encode keys and let go of their pixels. A texture whose lossless call could
        still flip once the pending slot binds it waits.
        """
        ready: list[str] = []
        for key, texture in self.textures.items():
            if key not in self._images or key not in keys:
                continue
            slots = self._slots.get(key, set())
            settled = (
                pending is None
                or BUMP_SLOT in slots
                or self.encoding.is_lossless(slots)
                == self.encoding.is_lossless(slots | {pending})
            )
            if not settled:
                continue
            texture.normal = BUMP_SLOT in slots
            texture.lossless = self.encoding.is_lossless(slots)
            if texture.normal:
                self._images[key] = decode_ag_normal(self._images[key])
            ready.append(key)

        if not ready:
            return
        with ThreadPoolExecutor(ENCODE_WORKERS) as pool:
            encoded = pool.map(
                encode_webp,
                [self._images.pop(key) for key in ready],
                [self.textures[key].lossless for key in ready],
            )
            for key, payload in zip(ready, encoded):
                self.textures[key].webp = payload

    def finish(self, keys: set[str]) -> dict[str, Texture]:
        """
        Drop every texture outside keys, encode whatever still waits, and hand
        back the result.
        """
        orphans = set(self.textures) - keys
        if orphans:
            logger.warning(f"{len(orphans)} textures dropped before encode")
        for key in orphans:
            self.textures.pop(key, None)
            self._images.pop(key, None)
            self._slots.pop(key, None)
        self.encode(set(self.textures), None)
        return self.textures


def sum_encoded_bytes(textures: dict[str, Texture]) -> int:
    return sum(len(texture.webp) for texture in textures.values())


def decode_ag_normal(image: Image.Image) -> Image.Image:
    """
    Unpack an AG-stored normal map into an ordinary RGB one.

    PGR stores X in alpha with R pinned to 1 and B duplicated from G, in every
    texture format in the roster.
    """
    channels = np.asarray(image.convert("RGBA"), np.float32) / 255.0
    x = channels[..., 3] * channels[..., 0]
    y = channels[..., 1]
    z = np.sqrt(np.clip(1.0 - (2 * x - 1) ** 2 - (2 * y - 1) ** 2, 0.0, 1.0))
    normal = np.stack([x, y, (z + 1.0) * 0.5], axis=-1)
    return Image.fromarray(np.round(normal * 255.0).astype(np.uint8), "RGB")


def _convert_wrap(mode: int, where: str) -> int:
    resolved = WRAP_MODES.get(mode)
    if resolved is None:
        logger.warning(f"{where}: unrecognized wrap mode {mode}, emitting repeat")
        return REPEAT
    return resolved
