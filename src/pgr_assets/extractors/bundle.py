import logging
import os
from typing import Any, cast

import UnityPy
from PIL import Image
from UnityPy.classes import Sprite, TextAsset, Texture2D
from UnityPy.enums import ClassIDType

from pgr_assets.asset_paths import THUMBNAIL_FORCED_ASPECTS, THUMBNAIL_IMAGE_SIZES
from pgr_assets.converters.binarytable.exceptions import BinaryTableError
from pgr_assets.image_names import resolve_image_stems

from .helpers import rewrite_text_asset

logger = logging.getLogger("pgr-assets.extractors.bundle")


def extract_bundle(
    env: UnityPy.Environment,
    output_dir: str,
    game_version: tuple[int, int],
    allow_binary_table_convert=False,
    ambiguous_images: dict[str, str] | None = None,
):
    ambiguous_images = ambiguous_images or {}

    for path, obj in env.container.items():
        dest = os.path.join(output_dir, *path.split("/"))
        # create dest based on original path
        # make sure that the dir of that path exists
        os.makedirs(os.path.dirname(dest), exist_ok=True)

        try:
            if path.endswith(".ttf"):
                font = next(
                    o
                    for o in cast(Any, obj).assets_file.objects.values()
                    if o.type == ClassIDType.Font
                )
                write_file(dest, bytes(font.read().m_FontData))
                logger.debug(f"Extracted font {path}")
            elif obj.type.name in ["Texture2D", "Sprite"]:
                data = cast(Texture2D | Sprite, obj.read())
                for stem in resolve_image_stems(path, ambiguous_images):
                    save_image(data.image, os.path.join(output_dir, *stem.split("/")))
                logger.debug(f"Extracted {path}")
            elif obj.type.name == "TextAsset":
                text = cast(TextAsset, obj.read())
                dest, data = rewrite_text_asset(
                    dest,
                    text.m_Script.encode("utf-8", "surrogateescape"),
                    game_version,
                    allow_binary_table_convert=allow_binary_table_convert,
                )
                # path can change a bit
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                write_file(dest, data)
                logger.debug(f"Extracted {path}")
            # else:
            #     logger.warning(f"Unsupported type {obj.type.name} for {path}")
        except (BinaryTableError, UnicodeDecodeError) as e:
            logger.warning(f"Skipping {path}: {e}")
        except Exception:
            logger.exception(f"Unexpected failure extracting {path}")


def get_text_asset(
    env: UnityPy.Environment,
    path: str,
    game_version: tuple[int, int],
    allow_binary_table_convert=False,
) -> str:
    obj = env.container[path]
    text = cast(TextAsset, obj.read())
    _, data = rewrite_text_asset(
        path,
        text.m_Script.encode("utf-8", "surrogateescape"),
        game_version,
        allow_binary_table_convert=allow_binary_table_convert,
    )
    return data.decode("utf-8")


def write_file(dest: str, data: bytes | bytearray):
    tmp = f"{dest}.tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, dest)


def save_image_file(img: Image.Image, dest: str, **options):
    tmp = f"{dest}.tmp"
    img.save(tmp, format=os.path.splitext(dest)[1][1:], **options)
    os.replace(tmp, dest)


def save_image(img: Image.Image, dest: str):
    save_image_file(img, dest + ".png")
    save_image_file(img, dest + ".webp", lossless=False, quality=80)

    path = dest.replace(os.sep, "/")
    for marker, sizes in THUMBNAIL_IMAGE_SIZES.items():
        if marker not in path:
            continue
        aspect = THUMBNAIL_FORCED_ASPECTS.get(marker)
        for size in sizes:
            if aspect is None:
                thumb = img.copy()
                thumb.thumbnail((size, size))
            else:
                width = min(size, img.width)
                thumb = img.resize(
                    (width, round(width / aspect)), Image.Resampling.LANCZOS
                )
            save_image_file(thumb, f"{dest}.{size}.webp", lossless=False, quality=80)
        break
