"""
The mesh and skin arrays: one primitive per part, morph targets appended last so
no accessor index moves once assigned.
"""

import logging

import pygltflib as gl

from pgr_assets.models.format import to_plain
from pgr_assets.models.gltf.buffer import Blob
from pgr_assets.models.gltf.materials import Shading
from pgr_assets.models.mesh import Geometry
from pgr_assets.models.part import Part

logger = logging.getLogger("pgr-assets")

# glTF multiplies COLOR_0 into base color, and the keywords that read these say
# shading control rather than tint, so emitting COLOR_0 would discolor every stock
# render.
COLOR_ATTRIBUTE = "_PGRCOLOR"
SMOOTH_NORMAL_ATTRIBUTE = "_PGRSMOOTHNORMAL"
ZONE_ATTRIBUTE = "_PGRZONE"

# Most authored morph weights are float noise far below this. Writing those would
# put a rest pose on nearly every face for no visible reason.
REST_TOLERANCE = 1e-3


class Meshes:
    def __init__(self, blob: Blob, shading: Shading, cleared: set[int]) -> None:
        self.meshes: list[gl.Mesh] = []
        self.skins: list[gl.Skin] = []
        self._blob = blob
        self._shading = shading
        self._cleared = cleared
        self._morph_parts: list[tuple[gl.Mesh, Geometry]] = []

    def add(self, part: Part, node: gl.Node) -> None:
        """
        Emit the part's primitive onto its node, and its skin when it has one.
        """
        blob = self._blob
        geometry = part.geometry
        attributes = emit_attributes(geometry, blob)
        if (
            part.skin is not None
            and geometry.joints is not None
            and geometry.weights is not None
        ):
            attributes.JOINTS_0 = blob.add_vec4_ushort(geometry.joints)
            attributes.WEIGHTS_0 = blob.add_vec4(geometry.weights)
            self.skins.append(
                gl.Skin(
                    joints=part.skin.joints,
                    inverseBindMatrices=blob.add_mat4(part.skin.inverse_bind),
                    skeleton=part.skin.root_bone,
                )
            )
            node.skin = len(self.skins) - 1
            # The joints place a skinned mesh and the renderer ignores this node's
            # transform. Clearing it only where the node has no children keeps that
            # true without moving anything that hangs off it.
            if part.node in self._cleared:
                node.translation = node.rotation = node.scale = None

        indices = blob.add_scalar(geometry.indices)
        mesh = gl.Mesh(
            name=geometry.name,
            primitives=[
                gl.Primitive(
                    attributes=attributes,
                    indices=indices,
                    material=self._shading.add(part.materials, geometry, part.winding),
                )
            ],
        )
        self.meshes.append(mesh)
        node.mesh = len(self.meshes) - 1
        if geometry.morphs:
            self._morph_parts.append((mesh, geometry))

    def finish(self) -> None:
        for mesh, geometry in self._morph_parts:
            emit_morphs(mesh, geometry, self._blob)


def emit_attributes(geometry: Geometry, blob: Blob) -> gl.Attributes:
    attributes = gl.Attributes(POSITION=blob.add_vec3(geometry.positions))
    if geometry.normals is not None:
        attributes.NORMAL = blob.add_vec3(geometry.normals)
        if geometry.tangents is not None:
            attributes.TANGENT = blob.add_vec4(geometry.tangents)
    elif geometry.tangents is not None:
        logger.warning(f"{geometry.name}: tangents without normals cannot be emitted")
    for slot, uvs in enumerate(geometry.uvs):
        setattr(attributes, f"TEXCOORD_{slot}", blob.add_vec2(uvs))
    if geometry.colors is not None:
        setattr(attributes, COLOR_ATTRIBUTE, blob.add_vec4(geometry.colors))
    if geometry.smooth_normal is not None:
        setattr(attributes, SMOOTH_NORMAL_ATTRIBUTE, blob.add_vec3(geometry.smooth_normal))
    if geometry.zones is not None:
        setattr(attributes, ZONE_ATTRIBUTE, blob.add_vec2(geometry.zones))
    return attributes


def emit_morphs(mesh: gl.Mesh, geometry: Geometry, blob: Blob) -> None:
    vertices = len(geometry.positions)
    base = mesh.primitives[0].attributes
    has_normal = base.NORMAL is not None
    has_tangent = base.TANGENT is not None
    targets: list[gl.Attributes] = []
    target_names: list[str] = []
    weights: list[float] = []
    for morph in geometry.morphs:
        # pygltflib types Primitive.targets as list[Attributes], so a plain
        # dict serializes but fails the type check.
        index_view = blob.add_index_view(morph.indices)
        target = gl.Attributes(
            POSITION=blob.add_sparse_vec3(index_view, morph.positions, vertices)
        )
        if has_normal and morph.normals is not None:
            target.NORMAL = blob.add_sparse_vec3(index_view, morph.normals, vertices)
        if has_tangent and morph.tangents is not None:
            target.TANGENT = blob.add_sparse_vec3(index_view, morph.tangents, vertices)
        targets.append(target)
        target_names.append(morph.name)
        weights.append(morph.rest_influence)

    mesh.primitives[0].targets = targets or None
    mesh.extras = to_plain({"targetNames": target_names}) if target_names else None
    if any(abs(weight) > REST_TOLERANCE for weight in weights):
        mesh.weights = weights
