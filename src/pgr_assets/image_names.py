import os
from collections.abc import Iterable

from pgr_assets.asset_paths import IMAGE_SOURCE_EXTENSIONS, TEXTURE_BUNDLE_MARKER

_IMAGE_REFERENCE_PREFIX = "assets/product/texture/"


def split_image_ext(path: str) -> tuple[str, str]:
    stem, ext = os.path.splitext(path)

    if ext.lower() not in IMAGE_SOURCE_EXTENSIONS:
        return path, ""

    return stem, ext.lower()


def find_ambiguous_images(bundles: Iterable[str]) -> dict[str, str]:
    claims: dict[str, set[str]] = {}

    for bundle in bundles:
        name = bundle.lower()
        if not name.startswith(TEXTURE_BUNDLE_MARKER) or not name.endswith(".ab"):
            continue

        stem, ext = split_image_ext(name[: -len(".ab")])
        if ext:
            claims.setdefault(stem, set()).add(ext)

    return {stem: min(exts) for stem, exts in claims.items() if len(exts) > 1}


def resolve_image_stems(path: str, ambiguous: dict[str, str]) -> list[str]:
    stem, ext = os.path.splitext(path)

    winner = ambiguous.get(stem.lower())
    if winner is None:
        return [stem]

    if ext.lower() != winner:
        return [f"{stem}{ext.lower()}"]

    return [stem, f"{stem}{ext.lower()}"]


def make_image_reference(stem: str) -> str:
    return stem.lower().removeprefix(_IMAGE_REFERENCE_PREFIX)
