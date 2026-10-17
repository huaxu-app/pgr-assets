import logging
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from typing import Any

from UnityPy.classes import PPtr

from pgr_assets.models.library import CubemapLibrary
from pgr_assets.models.material import MaterialSet, Surface, read_material_set
from pgr_assets.models.part import Part
from pgr_assets.models.prefab import Prefab
from pgr_assets.models.texture import EYE_MASK_SLOT, TextureSet
from pgr_assets.models.unity import read_tree

logger = logging.getLogger("pgr-assets")

SKIN_DISPLAY = "XCharSkinDisplay"
HAIR_EYE = "XHairEyeTransparent"
ALTERNATE_SCRIPTS = (SKIN_DISPLAY, HAIR_EYE)


@dataclass
class SwapEntry:
    part: int
    # None on a hide-only entry.
    materials: MaterialSet | None
    hide: bool

    def swaps_material(self, parts: list[Part]) -> bool:
        """
        Whether the entry puts a material on the part other than its own.
        """
        own = parts[self.part].materials.main.key
        return self.materials is not None and self.materials.main.key != own


@dataclass
class PartSwap:
    part_id: int
    entries: list[SwapEntry]


@dataclass
class EyeMask:
    part: int
    texture: str | None


@dataclass
class HairFade:
    part: int
    materials: MaterialSet
    fade_distance: float
    eyes: list[EyeMask]
    additional: SwapEntry | None
    check_node: int | None = None
    eye_alpha_blending: bool = False


@dataclass
class Alternates:
    parts: list[PartSwap] = field(default_factory=list)
    hair: list[HairFade] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.parts or self.hair)


@dataclass
class Pointers:
    prefab: Prefab
    component: Any
    part_of_node: dict[int, int]
    textures: TextureSet
    cubemaps: CubemapLibrary

    def resolve_part(self, pointer: Any) -> int | None:
        node = self.prefab.resolve_node(self.component, pointer)
        return None if node is None else self.part_of_node.get(node)

    def read_materials(self, pointer: Any, where: str) -> MaterialSet | None:
        resolved = self.resolve_pptr(pointer)
        if resolved is None:
            return None
        return read_material_set(resolved, self.textures, self.cubemaps, where)

    def resolve_pptr(self, pointer: Any) -> PPtr | None:
        return self.prefab.resolve_pointer(self.component, pointer)


def read_alternates(
    prefab: Prefab, parts: list[Part], textures: TextureSet, cubemaps: CubemapLibrary
) -> Alternates:
    alternates = Alternates()
    part_of_node = {part.node: index for index, part in enumerate(parts)}

    for node, script, component in prefab.find_components(*ALTERNATE_SCRIPTS):
        name = prefab.nodes[node].name
        tree = read_tree(component, name, script, lambda tree: tree)
        if tree is None:
            continue
        pointers = Pointers(prefab, component, part_of_node, textures, cubemaps)
        try:
            if script == SKIN_DISPLAY:
                alternates.parts.extend(read_skin_display(tree, pointers, name, parts))
            elif script == HAIR_EYE:
                fade = read_hair_eye(tree, pointers, name)
                if fade is not None:
                    alternates.hair.append(fade)
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as error:
            logger.warning(
                f"{name}: {script} malformed, {type(error).__name__}: {error}"
            )

    return alternates


def read_skin_display(
    tree: dict, pointers: Pointers, where: str, parts: list[Part]
) -> list[PartSwap]:
    swaps: list[PartSwap] = []
    for group in tree["PartDataArr"]:
        entries: list[SwapEntry] = []
        for data in group["DataArr"]:
            part = pointers.resolve_part(data["Render"])
            if part is None:
                logger.warning(f"{where}: {SKIN_DISPLAY} names a renderer with no part")
                continue

            hide = bool(data["HideRenderer"])
            materials = pointers.read_materials(data["Mat"], where)
            if materials is None and not hide:
                logger.warning(f"{where}: {SKIN_DISPLAY} entry has no usable material")
                continue

            if materials is not None:
                materials = replace(materials, passes=parts[part].materials.passes)
            entries.append(SwapEntry(part, materials, hide))

        if entries:
            swaps.append(PartSwap(int(group["MatPartId"]), entries))
    return swaps


def read_hair_eye(tree: dict, pointers: Pointers, where: str) -> HairFade | None:
    part = pointers.resolve_part(tree["HairRenderer"])
    if part is None:
        logger.warning(f"{where}: {HAIR_EYE} names a hair renderer with no part")
        return None

    materials = pointers.read_materials(tree["HairTransparentMat"], where)
    if materials is None:
        logger.warning(f"{where}: {HAIR_EYE} has no usable transparent material")
        return None

    masks = tree["EyeMaskTextures"]
    eyes: list[EyeMask] = []
    for index, renderer in enumerate(tree["EyeRenderers"]):
        eye = pointers.resolve_part(renderer)
        if eye is None:
            logger.warning(
                f"{where}: {HAIR_EYE} eye {index} names a renderer with no part"
            )
            continue

        raw = masks[index] if index < len(masks) else None
        pointer = pointers.resolve_pptr(raw)
        texture = pointers.textures.add(pointer, EYE_MASK_SLOT, where)
        if texture is None and pointer is not None:
            logger.warning(
                f"{where}: {HAIR_EYE} eye {index} mask unreadable, it stamps the whole eye"
            )
        eyes.append(EyeMask(eye, texture))

    return HairFade(
        part=part,
        materials=materials,
        fade_distance=float(tree["FadeDistance"]),
        eyes=eyes,
        additional=_read_additional(tree, pointers, where),
        check_node=pointers.prefab.resolve_node(pointers.component, tree["CheckNode"]),
        # Most prefabs predate the field. The 4.7.0 ctor defaults it to true.
        eye_alpha_blending=bool(tree.get("EnableEyeAlphaBlending", True)),
    )


def _read_additional(tree: dict, pointers: Pointers, where: str) -> SwapEntry | None:
    if not tree["AdditionalRenderer"]:
        return None

    part = pointers.resolve_part(tree["AdditionalHairRenderer"])
    materials = pointers.read_materials(tree["AdditionalHairTransparentMat"], where)
    if part is None or materials is None:
        logger.warning(f"{where}: {HAIR_EYE} additional hair does not resolve")
        return None
    return SwapEntry(part, materials, False)


def iter_alternate_materials(alternates: Alternates) -> Iterator[tuple[int, MaterialSet]]:
    for swap in alternates.parts:
        for entry in swap.entries:
            if entry.materials is not None:
                yield entry.part, entry.materials
    for fade in alternates.hair:
        yield fade.part, fade.materials
        if fade.additional is not None and fade.additional.materials is not None:
            yield fade.additional.part, fade.additional.materials


def iter_surfaces(parts: list[Part], alternates: Alternates) -> Iterator[Surface]:
    for part in parts:
        yield from part.materials.surfaces
    for _, materials in iter_alternate_materials(alternates):
        yield from materials.surfaces


def resolve_initial_set(alternates: Alternates, parts: list[Part]) -> int | None:
    """
    The part set the model spawns in. No set is authored as the default. At spawn
    nothing is swapped, which is whichever set keeps every renderer's own material
    and hides nothing.
    """
    for swap in alternates.parts:
        if not any(e.hide or e.swaps_material(parts) for e in swap.entries):
            return swap.part_id
    return None
