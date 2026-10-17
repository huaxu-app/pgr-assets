from dataclasses import dataclass, field

from pgr_assets.models.alternates import Alternates, iter_surfaces
from pgr_assets.models.faces import FaceRig
from pgr_assets.models.part import Part
from pgr_assets.models.prefab import Node, ObjectTag, find_node
from pgr_assets.models.rig import Skin
from pgr_assets.models.shadow import ProjectionShadow, SelfShadow
from pgr_assets.models.springs import Springs
from pgr_assets.models.texture import Texture

# The transforms the engine looks up by name: the hair fade measures to the head
# when its component names no node, and the rig moves as one under Bip001.
HEAD_BONE = "Bip001Head"
BODY_BONE = "Bip001"


@dataclass
class Scene:
    """
    Detached from UnityPy: nothing here holds a reader, which is what lets the env
    evict a target's bundles once the build returns.
    """

    name: str
    nodes: list[Node] = field(default_factory=list)
    parts: list[Part] = field(default_factory=list)
    object_tags: list[ObjectTag] = field(default_factory=list)
    springs: Springs = field(default_factory=Springs)
    self_shadow: SelfShadow | None = None
    projection_shadow: ProjectionShadow | None = None
    textures: dict[str, Texture] = field(default_factory=dict)
    alternates: Alternates = field(default_factory=Alternates)
    faces: FaceRig | None = None

    @property
    def head(self) -> int | None:
        return find_node(self.nodes, HEAD_BONE)

    @property
    def body(self) -> int | None:
        return find_node(self.nodes, BODY_BONE)

    @property
    def skins(self) -> list[Skin]:
        return [part.skin for part in self.parts if part.skin is not None]

    @property
    def cubemaps(self) -> set[str]:
        """
        The shared cubemaps any surface of the scene names.
        """
        return {
            surface.cubemap
            for surface in iter_surfaces(self.parts, self.alternates)
            if surface.cubemap is not None
        }


def find_cleared_nodes(nodes: list[Node], parts: list[Part]) -> set[int]:
    """
    Nodes whose own transform glTF requires a viewer to ignore.
    """
    return {
        part.node
        for part in parts
        if part.skin is not None
        and part.geometry.joints is not None
        and part.geometry.weights is not None
        and not nodes[part.node].child_count
    }


def collect_skin_joints(parts: list[Part]) -> set[int]:
    return {
        joint
        for part in parts
        if part.skin is not None
        for slot, joint in enumerate(part.skin.joints)
        if slot not in part.skin.unresolved
    }
