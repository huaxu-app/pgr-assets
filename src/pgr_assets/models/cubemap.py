import logging
from dataclasses import dataclass
from typing import Any

from PIL import Image

from pgr_assets.models.format import CubemapEncoding, CubemapRow
from pgr_assets.models.texture import encode_webp, read_color_space
from pgr_assets.models.unity import decode_image, read_texture_bytes

logger = logging.getLogger("pgr-assets")

FACES = 6
DXT1 = 10
# DXT1 packs 4x4 texel blocks into 8 bytes.
DXT1_BLOCK = 4
DXT1_BLOCK_BYTES = 8

# The shader reconstructs radiance as rgb * a * 6.
RGBM: CubemapEncoding = "RGBM6"
LDR: CubemapEncoding = "LDR6"

IMAGE_SUFFIX = ".webp"


@dataclass
class Cubemap:
    """
    One webp per cubemap: mips stacked top to bottom from the largest, each mip a
    row of six faces in Unity's order, +X -X +Y -Y +Z -Z.
    """

    name: str
    key: str
    face_size: int
    mips: int
    encoding: CubemapEncoding
    color_space: str
    image: bytes = b""

    def as_dict(self) -> CubemapRow:
        return {
            "name": self.name,
            "key": self.key,
            "faceSize": self.face_size,
            "mips": self.mips,
            "encoding": self.encoding,
            "colorSpace": self.color_space,
        }


def resolve_level_offsets(
    face_size: int, mips: int, texture_format: int
) -> list[tuple[int, int, int]]:
    """
    Offset, length and edge size of every mip level within one face.
    """
    levels = []
    offset = 0
    for mip in range(mips):
        size = max(1, face_size >> mip)
        length = (
            max(1, (size + DXT1_BLOCK - 1) // DXT1_BLOCK) ** 2 * DXT1_BLOCK_BYTES
            if texture_format == DXT1
            else size * size * 4
        )
        levels.append((offset, length, size))
        offset += length
    return levels


def read_cubemap(texture: Any, key: str, where: str) -> Cubemap | None:
    name = texture.m_Name
    texture_format = int(texture.m_TextureFormat)
    face_size = int(texture.m_Width)
    mips = int(texture.m_MipCount)
    stride = int(texture.m_CompleteImageSize)

    offsets = resolve_level_offsets(face_size, mips, texture_format)
    offset, length, _ = offsets[-1]
    if offset + length != stride:
        logger.warning(
            f"{where}: cubemap {name} has an unexpected layout,"
            f" {mips} mips of format {texture_format} predict"
            f" {offset + length} bytes per face but it stores {stride}"
        )
        return None

    try:
        data = read_texture_bytes(texture)
        stack = Image.new("RGBA", (face_size * FACES, sum(size for *_, size in offsets)))
        top = 0
        for offset, length, size in offsets:
            for face in range(FACES):
                start = face * stride + offset
                image = decode_image(texture, data[start : start + length], size)
                stack.paste(image.convert("RGBA"), (face * size, top))
            top += size
    except Exception as error:  # noqa: BLE001  a bad decode costs one binding
        logger.warning(
            f"{where}: cubemap {name} did not decode, {type(error).__name__}: {error}"
        )
        return None

    return Cubemap(
        name=name,
        key=key,
        face_size=face_size,
        mips=mips,
        encoding=LDR if texture_format == DXT1 else RGBM,
        color_space=read_color_space(texture),
        image=encode_webp(stack, texture_format != DXT1),
    )
