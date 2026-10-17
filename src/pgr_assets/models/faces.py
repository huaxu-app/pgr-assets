import logging
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pgr_assets.models.part import Part
from pgr_assets.models.prefab import Prefab
from pgr_assets.models.texture import TextureSet
from pgr_assets.models.unity import read_pointer, read_tree

logger = logging.getLogger("pgr-assets")

FACE_SCRIPT = "XFaceAnimation"
FACE_INFO_SCRIPT = "XFaceInfo"
FACE_STATE_SCRIPT = "XFaceAnimationState"
FACE_SLOT = "_FaceMap"
FACE_KEYWORD = "_FACE"
NAME_FUNCTION = "FrameEventFaceName"
FACE_FUNCTIONS = frozenset(
    {"FrameEventFaceTex", "ChangeFaceTex", "OnEnterState", NAME_FUNCTION}
)


@dataclass
class FaceRig:
    """
    Renderer binding and texture keys indexed by face events.
    """

    node: int
    keys: list[str] = field(default_factory=list)


class FaceMode(Enum):
    # Set the slot, frame face events still change it.
    SET = "set"
    # Set the slot and ignore frame face events until the state exits.
    LOCK = "lock"
    # No face behavior at all, so whatever face is up stays up.
    KEEP = "keep"


@dataclass(frozen=True)
class StateFace:
    """
    What entering a state does to the face, when it is not the usual reset.
    """

    mode: FaceMode
    slot: int | None = None


def _index_owners(controller: Any) -> dict[int, list[tuple[int, int]]]:
    """
    Behavior index to the (layer, state full path id) keys it is attached to.
    """
    description = controller.m_StateMachineBehaviourVectorDescription
    indices = description.m_StateMachineBehaviourIndices
    owners: defaultdict[int, list[tuple[int, int]]] = defaultdict(list)
    for key, span in description.m_StateMachineBehaviourRanges:
        for at in range(span.m_StartIndex, span.m_StartIndex + span.m_Count):
            owners[indices[at]].append((key.m_LayerIndex, key.m_StateID))
    return owners


class Faces:
    """
    Resolve event textures and names after reading their controller's XFaceInfo.
    """

    def __init__(self, node: int, textures: TextureSet, prefab: Prefab) -> None:
        self.rig = FaceRig(node)
        self._textures = textures
        self._prefab = prefab
        self._names: dict[str, Any] = {}
        # (layer, state) to the face set on entry, None for a reset, and HasFrameEvent.
        self._states: dict[tuple[int, int], tuple[Any, bool]] = {}

    def read_controller(self, controller: Any) -> None:
        self._names = {}
        self._states = {}
        owners = _index_owners(controller)
        found_info = False
        pointers: list[Any] = controller.m_StateMachineBehaviours or []
        for index, pointer in enumerate(pointers):
            behavior = read_pointer(pointer, self._prefab.name, "state behavior")
            if behavior is None:
                continue
            script = self._prefab.read_script_class(behavior)
            try:
                if script == FACE_INFO_SCRIPT and not found_info:
                    # Animator.GetBehaviour<XFaceInfo>() selects the first instance.
                    found_info = True
                    self._names = {
                        face.Name: face.Icon for face in behavior.FaceList or ()
                    }
                elif script == FACE_STATE_SCRIPT:
                    icon = behavior.FaceIconPath
                    shown = icon if icon.m_PathID else None
                    for key in owners.get(index, ()):
                        self._states[key] = (shown, bool(behavior.HasFrameEvent))
            except AttributeError as error:
                logger.warning(
                    f"{self._prefab.name}: {script} behavior malformed, {error}"
                )

    def resolve_slot(self, event: Any, clip: str) -> int | None:
        if event.functionName == NAME_FUNCTION:
            pointer = self._names.get(event.data)
            if pointer is None:
                logger.warning(
                    f"{clip}: face {event.data!r} is not in the controller's"
                    f" {FACE_INFO_SCRIPT}, event dropped"
                )
                return None
        else:
            pointer = event.objectReferenceParameter

        key = self._textures.add(pointer, FACE_SLOT, self._prefab.name)
        if key is None:
            logger.warning(
                f"{clip}: {event.functionName} has no texture, event dropped"
            )
            return None
        return self._intern_slot(key)

    def resolve_state_face(self, layer: int, path_id: int, state: str) -> StateFace | None:
        found = self._states.get((layer, path_id))
        if found is None:
            return StateFace(FaceMode.KEEP)
        icon, has_frame_event = found
        if icon is None:
            return None
        key = self._textures.add(icon, FACE_SLOT, self._prefab.name)
        if key is None:
            logger.warning(f"{state}: face on entry has no texture, reset instead")
            return None
        mode = FaceMode.SET if has_frame_event else FaceMode.LOCK
        return StateFace(mode, self._intern_slot(key))

    def _intern_slot(self, key: str) -> int:
        if key not in self.rig.keys:
            self.rig.keys.append(key)
        return self.rig.keys.index(key)


def read_faces(prefab: Prefab, parts: list[Part], textures: TextureSet) -> Faces | None:
    for _, _, component in prefab.find_components(FACE_SCRIPT):
        raw = read_tree(
            component, prefab.name, FACE_SCRIPT, lambda tree: tree["SkinnedMeshRenderer"]
        )
        if raw is None:
            return None
        node = prefab.resolve_node(component, raw)
        if node is None:
            logger.warning(f"{prefab.name}: {FACE_SCRIPT} binds no renderer")
            return None
        if not any(
            part.node == node and FACE_KEYWORD in part.materials.main.keywords
            for part in parts
        ):
            logger.warning(
                f"{prefab.name}: {FACE_SCRIPT} binds a surface without {FACE_KEYWORD},"
                " faces never show"
            )
            return None
        return Faces(node, textures, prefab)
    return None
