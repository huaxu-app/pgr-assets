"""
The node array: one glTF node per prefab transform, with the shadow flags the
shader scripts pin on it.
"""

import pygltflib as gl

from pgr_assets.models.format import NodeExtras, to_plain
from pgr_assets.models.gltf.materials import Shading
from pgr_assets.models.scene import Scene

IDENTITY_T = [0.0, 0.0, 0.0]
IDENTITY_R = [0.0, 0.0, 0.0, 1.0]
IDENTITY_S = [1.0, 1.0, 1.0]


def emit_nodes(scene: Scene, shading: Shading) -> list[gl.Node]:
    self_shadow = scene.self_shadow
    projection = scene.projection_shadow
    casts_no_shadow = self_shadow.hide_casters if self_shadow else set()
    receives_no_shadow = self_shadow.dont_receive if self_shadow else set()
    projects_no_shadow = projection.no_shadow if projection else set()
    # XCharShadowInfo's alpha pairing for the projected ground shadow.
    shadow_alpha = {
        node: index
        for node, key in (projection.alpha if projection else ())
        if (index := shading.texture_of.get(key)) is not None
    }

    nodes = [
        gl.Node(
            name=node.name,
            translation=None if node.translation == IDENTITY_T else node.translation,
            rotation=None if node.rotation == IDENTITY_R else node.rotation,
            scale=None if node.scale == IDENTITY_S else node.scale,
            extras=to_plain(
                resolve_node_extras(
                    index in casts_no_shadow,
                    index in receives_no_shadow,
                    index in projects_no_shadow,
                    shadow_alpha.get(index),
                )
            ),
        )
        for index, node in enumerate(scene.nodes)
    ]

    for index, node in enumerate(scene.nodes):
        if node.parent is None:
            continue
        parent = nodes[node.parent]
        parent.children = [*(parent.children or []), index]
    return nodes


def resolve_node_extras(
    hides_caster: bool,
    hides_receiver: bool,
    hides_projection: bool,
    shadow_alpha: int | None,
) -> NodeExtras | None:
    extras: NodeExtras = {}
    if hides_caster:
        extras["castsShadow"] = False
    if hides_receiver:
        extras["receivesShadow"] = False
    if hides_projection:
        extras["castsProjectionShadow"] = False
    if shadow_alpha is not None:
        extras["projectionShadowAlpha"] = shadow_alpha
    return extras or None
