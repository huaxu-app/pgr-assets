"""
Stateless readers over UnityPy objects: identities, pointers, typetrees, curves.
Nothing here loads a bundle, that's ModelEnv's job.
"""

import logging
import math
from collections.abc import Callable
from typing import Any

from PIL import Image
from UnityPy.classes import PPtr
from UnityPy.export import Texture2DConverter
from UnityPy.files import BundleFile, SerializedFile
from UnityPy.helpers import ResourceReader

from pgr_assets.models.format import Curve

logger = logging.getLogger("pgr-assets")


def list_serialized_files(bundle_file: Any) -> dict[str, SerializedFile]:
    """
    The parsed files in a bundle, keyed by cab name.

    A bundle also carries raw readers for resource streams, which hold no
    objects, and env.files can hold entries that are not bundles at all.
    """
    if not isinstance(bundle_file, BundleFile):
        return {}
    return {
        str(cab): f
        for cab, f in bundle_file.files.items()
        if isinstance(f, SerializedFile)
    }


def resolve_asset_key(obj: Any) -> str:
    """
    Identity of a read object, stable across eviction.
    """
    return resolve_reader_key(obj.object_reader)


def resolve_reader_key(reader: Any) -> str:
    return f"{reader.assets_file.name}:{reader.path_id}"


def make_pointer(assets_file: Any, raw: Any) -> PPtr | None:
    """
    A raw typetree PPtr as a live pointer, or None when it points at nothing.
    """
    if not isinstance(raw, dict) or not raw.get("m_PathID"):
        return None
    return PPtr(
        m_FileID=raw["m_FileID"], m_PathID=raw["m_PathID"], assetsfile=assets_file
    )


def resolve_pointer_key(assets_file: Any, raw: Any) -> str | None:
    """
    Identity of a raw typetree PPtr's target, or None when it does not resolve.
    """
    pointer = make_pointer(assets_file, raw)
    if pointer is None:
        return None
    try:
        return resolve_reader_key(pointer.deref())
    except Exception as error:  # noqa: BLE001  the caller decides what a miss costs
        logger.debug(f"pointer unresolved, {type(error).__name__}: {error}")
        return None


def read_tree[T](
    component: Any, owner: str, what: str, parse: Callable[[dict], T]
) -> T | None:
    """
    A component's typetree through `parse`, or None after a warning. A field the
    script lacks lands here as a KeyError. The caller says what a miss costs.
    """
    try:
        return parse(component.object_reader.read_typetree())
    except Exception as error:  # noqa: BLE001
        logger.warning(f"{owner}: {what} unreadable, {type(error).__name__}: {error}")
        return None


def read_pointer(pointer: Any, owner: str, what: str) -> Any | None:
    """
    The object a live PPtr names, None when it names nothing or after a warning.
    """
    if pointer is None or not pointer.m_PathID:
        return None
    try:
        return pointer.read()
    except Exception as error:  # noqa: BLE001
        logger.warning(f"{owner}: {what} unreadable, {type(error).__name__}: {error}")
        return None


def resolve_external_path(pointer: Any) -> str | None:
    """
    The file a live PPtr points out of its own serialized file into, None when it
    points inside.
    """
    file_id = pointer.m_FileID
    if not file_id:
        return None
    externals = pointer.assetsfile.externals
    if file_id > len(externals):
        return None
    return str(externals[file_id - 1].path)


def read_matrix4(pose: Any) -> list[list[float]]:
    return [[getattr(pose, f"e{row}{column}") for column in range(4)] for row in range(4)]


def read_uv_channel(handler: Any, channel: int) -> Any:
    return getattr(handler, f"m_UV{channel}")


def read_texture_bytes(texture: Any) -> bytes:
    """
    A texture's pixel block, streamed from its resource file or inline.
    """
    stream = texture.m_StreamData
    if stream is not None and stream.path:
        return ResourceReader.get_resource_data(
            stream.path,
            texture.object_reader.assets_file,
            stream.offset,
            stream.size,
        )
    return bytes(texture.image_data)


def decode_image(texture: Any, data: bytes, size: int) -> Image.Image:
    """
    One square level of a texture's pixel block, in the texture's own format.
    """
    reader = texture.object_reader
    return Texture2DConverter.parse_image_data(
        data, size, size, texture.m_TextureFormat, reader.version, reader.platform
    )


def list_dependencies(bundle_file: Any) -> list[str]:
    """
    The m_Dependencies of every AssetBundle object in one loaded bundle.
    """
    deps: list[str] = []
    for serialized in list_serialized_files(bundle_file).values():
        # SerializedFile.__init__ already parsed this. Re-reading the object
        # costs a full m_Container parse, thousands of PPtrs on a big bundle.
        bundle: Any = serialized.assetbundle
        if bundle is not None:
            deps += bundle.m_Dependencies or []
    return [d.lower() for d in deps]


# A Unity stepped key carries an infinite tangent, and a bare `Infinity` in the JSON
# chunk fails JSON.parse on the whole glb rather than on this block.
STEEP = 1.0e6


def _clamp_finite(value: float) -> float:
    if math.isnan(value):
        return 0.0
    return max(-STEEP, min(STEEP, value))


def read_curve(raw: Any) -> Curve:
    """
    An AnimationCurve as `[time, value, inSlope, outSlope]` per key.
    """
    return [
        [k["time"], k["value"], _clamp_finite(k["inSlope"]), _clamp_finite(k["outSlope"])]
        for k in raw["m_Curve"]
    ]
