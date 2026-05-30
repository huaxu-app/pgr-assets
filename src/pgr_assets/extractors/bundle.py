import logging
import os
from typing import Any, cast

import UnityPy
from PIL import Image
from UnityPy.classes import Sprite, TextAsset, Texture2D
from UnityPy.enums import ClassIDType

from pgr_assets.asset_paths import ROLECHARACTER_IMAGE_MARKER
from pgr_assets.converters.binarytable.exceptions import BinaryTableError

from .helpers import rewrite_text_asset

logger = logging.getLogger("pgr-assets.extractors.bundle")


def extract_bundle(
    env: UnityPy.Environment,
    output_dir: str,
    game_version: tuple[int, int],
    allow_binary_table_convert=False,
):
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
                with open(dest, "wb") as f:
                    f.write(bytes(font.read().m_FontData))
                logger.debug(f"Extracted font {path}")
            elif obj.type.name in ["Texture2D", "Sprite"]:
                data = cast(Texture2D | Sprite, obj.read())
                save_image(data.image, dest)
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
                with open(dest, "wb") as f:
                    f.write(data)
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


def save_image(img: Image.Image, dest: str):
    # correct extension
    dest, ext = os.path.splitext(dest)
    img.save(dest + ".png")
    img.save(dest + ".webp", lossless=False, quality=80)

    if ROLECHARACTER_IMAGE_MARKER in dest.replace(os.sep, "/"):
        thumb = img.copy()
        thumb.thumbnail((256, 256))
        thumb.save(dest + ".256.webp", lossless=False, quality=80)
