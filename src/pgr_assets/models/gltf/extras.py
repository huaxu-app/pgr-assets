"""
The scene extras block: anchors, object tags, springs, shadows, faces and the
alternate material sets, each mapped onto the document's node and material indices.
"""

import itertools
import logging

from pgr_assets.models.alternates import EyeMask, resolve_initial_set
from pgr_assets.models.faces import FaceRig
from pgr_assets.models.format import (
    FORMAT_VERSION,
    AlternateEntryRow,
    AlternatesRow,
    EyeRow,
    FacesRow,
    HairFadeRow,
    PartSwapRow,
    SceneExtras,
)
from pgr_assets.models.gltf.materials import Shading
from pgr_assets.models.material import MaterialSet
from pgr_assets.models.part import Part
from pgr_assets.models.prefab import index_tags
from pgr_assets.models.scene import Scene

logger = logging.getLogger("pgr-assets")


def emit_scene_extras(scene: Scene, shading: Shading) -> SceneExtras:
    extras: SceneExtras = {
        "formatVersion": FORMAT_VERSION,
        "anchors": {"head": scene.head, "body": scene.body},
    }
    if scene.object_tags:
        extras["objectTags"] = [
            {"name": tag.name, "nodes": tag.nodes} for tag in scene.object_tags
        ]
    if scene.alternates:
        extras["alternates"] = emit_alternates(scene, shading)
    if scene.springs:
        extras["springBones"] = scene.springs.as_dict()
    if scene.self_shadow is not None:
        extras["selfShadow"] = scene.self_shadow.as_dict()
    if scene.faces is not None:
        faces = emit_faces(scene.faces, shading)
        if faces is not None:
            extras["faces"] = faces
    return extras


def emit_faces(rig: FaceRig, shading: Shading) -> FacesRow | None:
    """
    Map face slots to glTF textures without shifting event indices on a miss.
    """
    textures = [shading.texture_of.get(key) for key in rig.keys]
    if any(index is None for index in textures):
        logger.warning("a face texture is not in the glb, faces dropped")
        return None
    return {"node": rig.node, "textures": [i for i in textures if i is not None]}


def emit_alternates(scene: Scene, shading: Shading) -> AlternatesRow:
    parts: list[PartSwapRow] = []
    hair: list[HairFadeRow] = []
    tag_of_node = index_tags(scene.object_tags)
    # One material per part per swap, however often the swap names the part.
    emitted: dict[tuple[int, int], int] = {}
    groups = itertools.count()

    def emit_alternate(index: int, materials: MaterialSet, group: int) -> int:
        key = (index, group)
        if key not in emitted:
            part = scene.parts[index]
            emitted[key] = shading.add(materials, part.geometry, part.winding)
        return emitted[key]

    for swap in scene.alternates.parts:
        group = next(groups)
        entries: list[AlternateEntryRow] = []
        for entry in swap.entries:
            row: AlternateEntryRow = {
                "node": scene.parts[entry.part].node,
                "hide": entry.hide,
            }
            if entry.swaps_material(scene.parts):
                assert entry.materials is not None
                row["material"] = emit_alternate(entry.part, entry.materials, group)
            entries.append(row)
        parts.append({"partId": swap.part_id, "entries": entries})

    for fade in scene.alternates.hair:
        group = next(groups)
        fade_row: HairFadeRow = {
            "node": scene.parts[fade.part].node,
            "material": emit_alternate(fade.part, fade.materials, group),
            "fadeDistance": fade.fade_distance,
            "eyes": emit_eyes(scene.parts, shading, fade.eyes),
            # The game measures from Bip001Head when the component names nothing.
            "checkNode": scene.head if fade.check_node is None else fade.check_node,
        }
        tag = tag_of_node.get(fade_row["node"])
        if tag is not None:
            fade_row["set"] = tag
        if fade.eye_alpha_blending:
            fade_row["eyeAlphaBlending"] = True

        additional = fade.additional
        if additional is not None and additional.materials is not None:
            fade_row["additional"] = {
                "node": scene.parts[additional.part].node,
                "material": emit_alternate(additional.part, additional.materials, group),
            }
        hair.append(fade_row)

    block: AlternatesRow = {}
    if parts:
        block["parts"] = parts
    if hair:
        block["hairFade"] = hair
    initial = resolve_initial_set(scene.alternates, scene.parts)
    if initial is not None:
        block["initial"] = initial
    return block


def emit_eyes(parts: list[Part], shading: Shading, masks: list[EyeMask]) -> list[EyeRow]:
    eyes: list[EyeRow] = []
    for mask in masks:
        # A null mask stamps the whole eye.
        index = None if mask.texture is None else shading.texture_of.get(mask.texture)
        eyes.append({"node": parts[mask.part].node, "mask": index})
    return eyes
