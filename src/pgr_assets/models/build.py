import logging
from dataclasses import dataclass, replace
from itertools import chain

import numpy as np

from pgr_assets.lazyenv import LazyEnv
from pgr_assets.models import coords
from pgr_assets.models.alternates import (
    ALTERNATE_SCRIPTS,
    Alternates,
    iter_alternate_materials,
    iter_surfaces,
    read_alternates,
)
from pgr_assets.models.builtin import NAMES, read_builtin_geometry, resolve_builtin_key
from pgr_assets.models.clips import read_clips
from pgr_assets.models.emission import FLOW_SCRIPT, EmissionFlow, read_emission_flow
from pgr_assets.models.events import SOUND_SCRIPT, SYNC_SCRIPT
from pgr_assets.models.faces import FACE_SCRIPT, FACE_SLOT, read_faces
from pgr_assets.models.files import Publisher
from pgr_assets.models.library import CubemapLibrary
from pgr_assets.models.material import (
    ZONE_KEYWORDS,
    read_materials,
    resolve_uv3_layout,
)
from pgr_assets.models.mesh import Geometry, MorphChannel, Uv3Layout, read_geometry
from pgr_assets.models.model import Model
from pgr_assets.models.part import Part
from pgr_assets.models.prefab import (
    TAG_SCRIPT,
    Prefab,
    Renderer,
    read_object_tags,
    resolve_transform_paths,
)
from pgr_assets.models.registry import ModelEntry
from pgr_assets.models.rig import Skin, read_skin
from pgr_assets.models.scene import Scene, collect_skin_joints, find_cleared_nodes
from pgr_assets.models.scope import Run
from pgr_assets.models.shadow import (
    SHADOW_SCRIPTS,
    ProjectionShadow,
    read_shadow,
)
from pgr_assets.models.springs import SPRING_SCRIPTS, read_springs
from pgr_assets.models.tables import Tables
from pgr_assets.models.texture import TextureEncoding, TextureSet
from pgr_assets.models.webclip import ClipWriter

logger = logging.getLogger("pgr-assets")

WALKED_SCRIPTS = (
    *ALTERNATE_SCRIPTS,
    TAG_SCRIPT,
    *SPRING_SCRIPTS,
    FLOW_SCRIPT,
    *SHADOW_SCRIPTS,
    SOUND_SCRIPT,
    SYNC_SCRIPT,
    FACE_SCRIPT,
)


@dataclass(frozen=True)
class BuildTools:
    """
    What every target of one run builds with.
    """

    env: LazyEnv
    tables: Tables
    cubemaps: CubemapLibrary
    textures: TextureEncoding


def build_target[E: ModelEntry](
    tools: BuildTools, run: Run[E], entry: E, publisher: Publisher
) -> Model:
    env, cubemaps = tools.env, tools.cubemaps
    bundle = f"{entry.model_path}.ab"
    env.require(bundle)
    prefab = Prefab.read(env, bundle, entry.model_path, WALKED_SCRIPTS)
    paths = resolve_transform_paths(prefab.nodes)
    textures = TextureSet(tools.textures)
    parts = _read_parts(prefab, textures, cubemaps, read_emission_flow(prefab))
    alternates = read_alternates(prefab, parts, textures, cubemaps)
    _check_uvs(prefab, parts, alternates)
    parts = fill_streams(parts, alternates)
    self_shadow, projection_shadow = read_shadow(prefab, textures)
    faces = read_faces(prefab, parts, textures)

    tags = read_object_tags(prefab)
    morph_channels = {
        (part.node, morph.name_hash): MorphChannel(
            index, morph.full_weight, morph.rest_influence
        )
        for part in parts
        for index, morph in enumerate(part.geometry.morphs)
    }
    writer = ClipWriter(
        publisher,
        prefab.nodes,
        find_cleared_nodes(prefab.nodes, parts),
        morph_channels,
        collect_skin_joints(parts),
    )
    referenced = collect_texture_keys(parts, alternates, projection_shadow)
    # Decoded pixels parked through the clip walk run to a gigabyte. Face events
    # can still bind more slots, so whatever that could flip waits.
    textures.encode(referenced, FACE_SLOT if faces is not None else None)
    clips = read_clips(env, entry.id, entry.list_clip_sources(), paths, writer, faces)
    # Face textures are only known once the clip events are read.
    face_keys = set(faces.rig.keys) if faces is not None else set()

    scene = Scene(
        name=prefab.name,
        nodes=prefab.nodes,
        parts=parts,
        object_tags=tags,
        springs=read_springs(prefab),
        self_shadow=self_shadow,
        projection_shadow=projection_shadow,
        textures=textures.finish(referenced | face_keys),
        alternates=alternates,
        faces=faces.rig if faces is not None and faces.rig.keys else None,
    )
    playback = run.build_playback(tools.tables, entry, prefab, tags, clips)
    return Model(scene, clips, playback)


def collect_texture_keys(
    parts: list[Part], alternates: Alternates, projection: ProjectionShadow | None
) -> set[str]:
    keys = {
        reference.key
        for surface in iter_surfaces(parts, alternates)
        for reference in surface.textures
    }
    keys.update(
        mask.texture
        for fade in alternates.hair
        for mask in fade.eyes
        if mask.texture is not None
    )
    if projection is not None:
        keys.update(key for _, key in projection.alpha)
    return keys


def _read_parts(
    prefab: Prefab,
    textures: TextureSet,
    cubemaps: CubemapLibrary,
    flows: dict[int, EmissionFlow],
) -> list[Part]:
    parts: list[Part] = []
    for renderer in prefab.renderers:
        name = prefab.nodes[renderer.node].name
        if renderer.mesh is None or renderer.mesh.m_PathID == 0:
            logger.debug(f"{name}: {type(renderer.component).__name__} has no mesh")
            continue

        try:
            materials = read_materials(
                renderer.component, textures, cubemaps, name, flows.get(renderer.node)
            )
            if materials is None:
                continue
            uv3 = resolve_uv3_layout(materials)
            read = _read_part_geometry(prefab, renderer, uv3, name)
        except Exception as error:  # noqa: BLE001  one bad mesh must not lose the target
            logger.warning(f"{name}: {type(error).__name__}: {error}")
            continue
        if read is None:
            continue

        geometry, skin = read
        if not len(geometry.positions) or not len(geometry.indices):
            logger.warning(f"{name}: {geometry.name} has no geometry")
            continue

        if skin is not None and geometry.joints is None:
            logger.warning(f"{name}: bones but no blend indices, left unskinned")
            skin = None

        if uv3 is Uv3Layout.SMOOTH_NORMAL and geometry.smooth_normal is None:
            logger.warning(f"{name}: {geometry.name} has no uv3, no outline direction")

        if geometry.smooth_normal is not None and not geometry.uvs:
            logger.warning(f"{name}: {geometry.name} had only uv3, textures dropped")

        # Cull front is cull back on reversed triangles, which plain glTF can draw.
        if materials.render.cull == "front":
            geometry = replace(geometry, indices=coords.reverse_winding(geometry.indices))
        parts.append(Part(renderer.node, geometry, materials, skin))

    return parts


def _read_part_geometry(
    prefab: Prefab, renderer: Renderer, uv3: Uv3Layout, name: str
) -> tuple[Geometry, Skin | None] | None:
    builtin_id = resolve_builtin_key(renderer.mesh)
    if builtin_id is not None:
        builtin = NAMES.get(builtin_id)
        geometry = read_builtin_geometry(builtin_id, builtin or name)
        if geometry is None:
            logger.warning(f"{name}: built-in {builtin or builtin_id} is not baked")
            return None
        return geometry, None

    mesh = renderer.mesh.read()
    skin = None
    rest: list[float] = []
    if renderer.skinned:
        skin = read_skin(prefab.node_of, renderer.component, mesh, name)
        rest = renderer.component.m_BlendShapeWeights or []
    return read_geometry(mesh, name, uv3, rest, skin), skin


def _check_uvs(prefab: Prefab, parts: list[Part], alternates: Alternates) -> None:
    """
    Warn where a binding samples a UV channel the mesh does not carry.
    """
    own = ((index, part.materials) for index, part in enumerate(parts))
    for index, materials in chain(own, iter_alternate_materials(alternates)):
        part = parts[index]
        geometry = part.geometry
        where = prefab.nodes[part.node].name
        if not geometry.uvs:
            if materials.main.textures:
                logger.warning(f"{where}: mesh has no UVs, no texture is emitted")
            continue
        for surface in materials.surfaces:
            for reference in surface.textures:
                if geometry.find_uv_slot(reference.source_uv) is None:
                    logger.warning(
                        f"{where}: {reference.slot} wants"
                        f" uv{reference.source_uv}, the mesh has none, reads zero"
                    )


def fill_streams(parts: list[Part], alternates: Alternates) -> list[Part]:
    """
    Unity feeds a stream the mesh lacks as its default, white for color and (0, 1)
    for uv1.zw. Writing the default out leaves readers one path, with or without.
    """
    keywords: list[set[str]] = [set() for _ in parts]
    colored = [False for _ in parts]
    sets = enumerate(part.materials for part in parts)
    for index, materials in chain(sets, iter_alternate_materials(alternates)):
        for surface in materials.surfaces:
            keywords[index].update(surface.keywords)
            colored[index] |= surface.reads_color

    filled: list[Part] = []
    for part, wanted, reads_color in zip(parts, keywords, colored, strict=True):
        geometry = part.geometry
        count = len(geometry.positions)
        if geometry.colors is None and reads_color:
            geometry = replace(geometry, colors=np.ones((count, 4), np.float32))
        if geometry.zones is None and wanted.intersection(ZONE_KEYWORDS):
            zones = np.tile(np.array([0.0, 1.0], np.float32), (count, 1))
            geometry = replace(geometry, zones=zones)
        filled.append(replace(part, geometry=geometry))
    return filled
