import logging
from dataclasses import dataclass, field
from typing import Any

from pgr_assets.models.format import SelfShadowRow, round5
from pgr_assets.models.prefab import Prefab
from pgr_assets.models.texture import TextureSet
from pgr_assets.models.unity import read_tree

logger = logging.getLogger("pgr-assets")

SELF_SHADOW_SCRIPT = "XCharShadowMap"
PROJECTION_SHADOW_SCRIPT = "XCharShadowInfo"
SHADOW_SCRIPTS = (SELF_SHADOW_SCRIPT, PROJECTION_SHADOW_SCRIPT)
ALPHA_SLOT = "_MainTex"


@dataclass
class SelfShadow:
    pitch: float
    yaw_offset: float
    hide_casters: set[int] = field(default_factory=set)
    dont_receive: set[int] = field(default_factory=set)

    def as_dict(self) -> SelfShadowRow:
        return {
            "pitch": round5(self.pitch),
            "yawOffset": round5(self.yaw_offset),
        }


@dataclass
class ProjectionShadow:
    """
    XCharShadowInfo, which configures the projected ground shadow and not the
    shadowmap.
    """

    alpha: list[tuple[int, str]] = field(default_factory=list)
    no_shadow: set[int] = field(default_factory=set)


@dataclass
class _Reader:
    """
    One shadow component, with the context its pointers resolve against.
    """

    component: Any
    prefab: Prefab
    textures: TextureSet
    where: str

    def resolve_renderer(self, raw: Any, field_name: str) -> int | None:
        if self.prefab.resolve_pointer(self.component, raw) is None:
            return None
        index = self.prefab.resolve_node(self.component, raw)
        if index is None:
            logger.warning(f"{self.where}: {field_name} does not resolve to a node")
        return index

    def resolve_renderers(self, tree: dict, name: str) -> set[int]:
        found = set()
        for slot, raw in enumerate(tree[name]):
            index = self.resolve_renderer(raw, f"{name}[{slot}]")
            if index is not None:
                found.add(index)
        return found

    def resolve_texture(self, raw: Any) -> str | None:
        pointer = self.prefab.resolve_pointer(self.component, raw)
        if pointer is None:
            return None
        return self.textures.add(pointer, ALPHA_SLOT, self.where)

    def read_self_shadow(self, tree: dict) -> SelfShadow:
        return SelfShadow(
            pitch=float(tree["ShadowmapOffsetYAngle"]),
            yaw_offset=float(tree["ShadowmapOffsetAngle"]),
            hide_casters=self.resolve_renderers(tree, "HideShadowCasterRenderers"),
            dont_receive=self.resolve_renderers(tree, "DontReceiveShadowRenderers"),
        )

    def read_projection_shadow(self, tree: dict) -> ProjectionShadow:
        renderers = tree["AlphaRenderers"]
        textures = tree["AlphaTextures"]
        alpha = []
        for slot in range(min(len(renderers), len(textures))):
            target = self.resolve_renderer(renderers[slot], f"AlphaRenderers[{slot}]")
            if target is None:
                continue
            key = self.resolve_texture(textures[slot])
            if key is not None:
                alpha.append((target, key))

        return ProjectionShadow(
            alpha=alpha,
            no_shadow=self.resolve_renderers(tree, "NoShadowRenderers"),
        )


def read_shadow(
    prefab: Prefab, textures: TextureSet
) -> tuple[SelfShadow | None, ProjectionShadow | None]:
    self_shadow: SelfShadow | None = None
    projection: ProjectionShadow | None = None

    for node, script, component in prefab.find_components(*SHADOW_SCRIPTS):
        name = prefab.nodes[node].name
        reader = _Reader(component, prefab, textures, name)
        if script == SELF_SHADOW_SCRIPT:
            self_shadow = read_tree(component, name, script, reader.read_self_shadow)
        else:
            projection = read_tree(component, name, script, reader.read_projection_shadow)

    return self_shadow, projection
