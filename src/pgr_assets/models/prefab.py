import logging
from collections.abc import Collection, Iterator, Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import Any, NamedTuple

import numpy as np
from UnityPy.classes import PPtr
from UnityPy.classes.generated import (
    MeshFilter,
    MonoBehaviour,
    ParticleSystemRenderer,
    SkinnedMeshRenderer,
    Transform,
)
from UnityPy.classes.generated import Renderer as UnityRenderer

from pgr_assets.models import coords
from pgr_assets.models.env import ModelEnv
from pgr_assets.models.unity import (
    make_pointer,
    read_pointer,
    read_tree,
    resolve_asset_key,
    resolve_pointer_key,
)

logger = logging.getLogger("pgr-assets")

TAG_SCRIPT = "XObjectContainer"


@dataclass
class Node:
    name: str
    parent: int | None
    translation: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    rotation: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 1.0])
    scale: list[float] = field(default_factory=lambda: [1.0, 1.0, 1.0])
    child_count: int = 0


@dataclass
class Renderer:
    node: int
    component: Any
    mesh: Any = None
    skinned: bool = False


@dataclass
class ObjectTag:
    """
    A named group of nodes the game hides and shows together.
    """

    name: str
    nodes: list[int]


class Script(NamedTuple):
    node: int
    name: str
    component: Any


@dataclass
class Prefab:
    """
    The walked hierarchy. Holds live UnityPy objects, so a Prefab must not outlive the target's pinned scope.
    """

    name: str
    nodes: list[Node] = field(default_factory=list)
    renderers: list[Renderer] = field(default_factory=list)
    hidden_skinned: set[int] = field(default_factory=set)
    # Asset key of every walked GameObject, Transform and renderer to its node.
    node_of: dict[str, int] = field(default_factory=dict)
    scripts: list[Script] = field(default_factory=list)
    wanted_scripts: Collection[str] = ()
    _script_names: dict[tuple[str, int, int], str] = field(default_factory=dict)

    @classmethod
    def read(
        cls, env: ModelEnv, bundle: str, path: str, scripts: Collection[str] = ()
    ) -> "Prefab":
        root: Any = env.find_object(bundle, path)
        prefab = cls(name=root.m_Name, wanted_scripts=scripts)
        prefab._walk_node(root, None, set())
        return prefab

    def _walk_node(self, game_object: Any, parent: int | None, seen: set[str]) -> None:
        key = resolve_asset_key(game_object)
        if key in seen:
            return

        seen.add(key)

        transform = renderer = mesh_filter = None
        wanted: list[tuple[str, Any]] = []
        for component in self._read_components(game_object):
            if isinstance(component, Transform):
                transform = component
            elif isinstance(component, UnityRenderer):
                renderer = component
            elif isinstance(component, MeshFilter):
                mesh_filter = component
            elif isinstance(component, MonoBehaviour):
                script = self.read_script_class(component)
                if script in self.wanted_scripts:
                    wanted.append((script, component))

        index = len(self.nodes)
        self.nodes.append(Node(game_object.m_Name, parent, *_read_local_trs(transform)))
        self.node_of[key] = index
        if parent is not None:
            self.nodes[parent].child_count += 1
        if transform is not None:
            self.node_of[resolve_asset_key(transform)] = index

        for script, component in wanted:
            self.scripts.append(Script(index, script, component))

        if renderer is not None:
            self._add_renderer(game_object, renderer, index, mesh_filter)

        if transform is None:
            return

        for child in transform.m_Children or ():
            self._walk_child(child, index, seen)

    def find_components(self, *names: str) -> list[Script]:
        return [script for script in self.scripts if script.name in names]

    def resolve_node(self, component: Any, raw: Any) -> int | None:
        """
        The node a raw typetree PPtr on `component` names, None off the prefab.
        """
        key = self.resolve_key(component, raw)
        return None if key is None else self.node_of.get(key)

    def resolve_key(self, component: Any, raw: Any) -> str | None:
        """
        The asset key a raw typetree PPtr on `component` names, None when unresolved.
        """
        return resolve_pointer_key(component.object_reader.assets_file, raw)

    def resolve_pointer(self, component: Any, raw: Any) -> PPtr | None:
        """
        A raw typetree PPtr on `component` as a live pointer, None when it names nothing.
        """
        return make_pointer(component.object_reader.assets_file, raw)

    def read_script_class(self, component: Any) -> str:
        pointer = component.m_Script
        # m_FileID indexes the externals of the file holding the component.
        key = (
            component.object_reader.assets_file.name,
            pointer.m_FileID,
            pointer.m_PathID,
        )
        if key not in self._script_names:
            # A null m_Script is Unity's "Missing Script", nothing reads it so
            # neither do we. An unreadable one already got its warning.
            script = read_pointer(pointer, self.name, "script")
            self._script_names[key] = "" if script is None else script.m_ClassName
        return self._script_names[key]

    def _add_renderer(
        self, game_object: Any, renderer: Any, index: int, mesh_filter: Any
    ) -> None:
        self.node_of[resolve_asset_key(renderer)] = index
        if isinstance(renderer, ParticleSystemRenderer):
            # VFX, never geometry. The node stays, the effect doesn't.
            return

        skinned = isinstance(renderer, SkinnedMeshRenderer)
        mesh = renderer.m_Mesh if skinned else mesh_filter and mesh_filter.m_Mesh
        if game_object.m_IsActive and renderer.m_Enabled:
            self.renderers.append(Renderer(index, renderer, mesh, skinned))
        elif skinned:
            self.hidden_skinned.add(index)

    def _walk_child(self, child: Any, parent: int, seen: set[str]) -> None:
        try:
            game_object = child.read().m_GameObject.read()
        except Exception as error:  # noqa: BLE001  a bad child costs a subtree, not the target
            logger.warning(
                f"child {child.m_PathID} unreadable, {type(error).__name__}: {error}"
            )
            return

        self._walk_node(game_object, parent, seen)

    @staticmethod
    def _read_components(game_object: Any) -> Iterator[Any]:
        for pair in game_object.m_Component:
            try:
                yield pair.component.read()
            except Exception as error:  # noqa: BLE001  one bad component must not kill a target
                logger.warning(
                    f"{game_object.m_Name}: component unreadable,"
                    f" {type(error).__name__}: {error}"
                )


def read_object_tags(prefab: Prefab) -> list[ObjectTag]:
    tags: list[ObjectTag] = []
    for _, _, component in prefab.find_components(TAG_SCRIPT):
        rows = partial(_read_tag_rows, prefab, component)
        tags += read_tree(component, prefab.name, "object container", rows) or []
    return tags


def _read_tag_rows(prefab: Prefab, component: Any, tree: dict) -> list[ObjectTag]:
    tags: list[ObjectTag] = []
    for row in tree["Nodes"]:
        name, authored = row["Tag"], row["GameObjects"]
        members = [
            node
            for raw in authored
            if (node := prefab.resolve_node(component, raw)) is not None
        ]
        if len(members) != len(authored):
            logger.warning(
                f"{prefab.name}: tag {name} lost"
                f" {len(authored) - len(members)} of {len(authored)} members"
            )
        tags.append(ObjectTag(name, members))
    return tags


def index_tags(tags: Sequence[ObjectTag]) -> dict[int, str]:
    """
    Node to the tag that owns it. Last row wins, ModelCase is authored first and
    holds nearly everything.
    """
    return {node: tag.name for tag in tags for node in tag.nodes}


def find_node(nodes: Sequence[Node], name: str) -> int | None:
    """
    The shallowest node of that name, ties by walk order.
    """
    named = [
        (measure_depth(nodes, index), index)
        for index, node in enumerate(nodes)
        if node.name == name
    ]
    return min(named)[1] if named else None


def measure_depth(nodes: Sequence[Node], index: int) -> int:
    count, parent = 0, nodes[index].parent
    while parent is not None:
        count, parent = count + 1, nodes[parent].parent
    return count


def resolve_transform_paths(nodes: list[Node]) -> list[str]:
    """
    Root-relative Unity transform path per node, the root itself excluded.
    """
    paths: list[str] = []
    for node in nodes:
        if node.parent is None:
            paths.append("")
            continue
        parent = paths[node.parent]
        paths.append(f"{parent}/{node.name}" if parent else node.name)
    return paths


def _read_local_trs(transform: Any) -> tuple[list[float], list[float], list[float]]:
    if transform is None:
        return [0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0], [1.0, 1.0, 1.0]

    p, q, s = (
        transform.m_LocalPosition,
        transform.m_LocalRotation,
        transform.m_LocalScale,
    )
    return (
        coords.flip_z(np.array([p.x, p.y, p.z])).tolist(),
        coords.conjugate_quat(np.array([q.x, q.y, q.z, q.w])).tolist(),
        [s.x, s.y, s.z],
    )
