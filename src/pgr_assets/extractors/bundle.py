import logging
import os

from PIL import Image
import UnityPy
from UnityPy.enums import ClassIDType

from .helpers import rewrite_text_asset

logger = logging.getLogger('pgr-assets.extractors.bundle')


def extract_bundle(env: UnityPy.Environment, output_dir: str, game_version: tuple[int, int], allow_binary_table_convert=False):
    for path, obj in env.container.items():
        dest = os.path.join(output_dir, *path.split("/"))
        # create dest based on original path
        # make sure that the dir of that path exists
        os.makedirs(os.path.dirname(dest), exist_ok=True)

        try:
            if path.endswith('.ttf'):
                font = next(o for o in obj.assetsfile.objects.values() if o.type == ClassIDType.Font)
                with open(dest, "wb") as f:
                    f.write(bytes(font.read().m_FontData))
                logger.debug(f"Extracted font {path}")
            elif obj.type.name in ["Texture2D", "Sprite"]:
                data = obj.read()
                save_image(data.image, dest)
                logger.debug(f"Extracted {path}")
            elif obj.type.name == "TextAsset":
                data = obj.read()
                dest, data = rewrite_text_asset(dest, data.m_Script.encode('utf-8', 'surrogateescape'), game_version, allow_binary_table_convert=allow_binary_table_convert)
                # path can change a bit
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as f:
                    f.write(data)
                logger.debug(f"Extracted {path}")
            # else:
            #     logger.warning(f"Unsupported type {obj.type.name} for {path}")
        except Exception as e:
            logger.error(f"Failed to extract {path}: {e}")


def get_text_asset(env: UnityPy.Environment, path: str, game_version: tuple[int, int], allow_binary_table_convert = False) -> str:
    obj = env.container[path]
    data = obj.read()
    _, data = rewrite_text_asset(path, data.m_Script.encode('utf-8', 'surrogateescape'), game_version, allow_binary_table_convert=allow_binary_table_convert)
    return data.decode("utf-8")


def save_image(img: Image, dest: str):
    # correct extension
    dest, ext = os.path.splitext(dest)
    img.save(dest + ".png")
    img.save(dest + ".webp", lossless=False, quality=80)

    if '/image/rolecharacter/' in dest:
        thumb = img.copy()
        thumb.thumbnail((256, 256))
        thumb.save(dest + ".256.webp", lossless=False, quality=80)
