import logging
import os

import UnityPy

from .helpers import rewrite_text_asset

logger = logging.getLogger('pgr-assets.extractors.bundle')


def extract_bundle(env: UnityPy.Environment, output_dir: str):
    for path, obj in env.container.items():
        dest = os.path.join(output_dir, *path.split("/"))
        # create dest based on original path
        # make sure that the dir of that path exists
        os.makedirs(os.path.dirname(dest), exist_ok=True)

        try:
            if obj.type.name in ["Texture2D", "Sprite"]:
                data = obj.read()
                # correct extension
                dest, ext = os.path.splitext(dest)
                dest = dest + ".png"
                data.image.save(dest)
                logger.debug(f"Extracted {path}")
            elif obj.type.name == "TextAsset":
                data = obj.read()
                dest, data = rewrite_text_asset(dest, data.script)
                with open(dest, "wb") as f:
                    f.write(data)
                logger.debug(f"Extracted {path}")
            else:
                logger.warning(f"Unsupported type {obj.type.name} for {path}")
        except Exception as e:
            logger.error(f"Failed to extract {path}: {e}")


def get_text_asset(env: UnityPy.Environment, path: str) -> str:
    obj = env.container[path]
    data = obj.read()
    _, data = rewrite_text_asset(path, data.script)
    return data.decode("utf-8")
