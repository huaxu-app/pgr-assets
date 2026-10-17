import logging
from dataclasses import dataclass, field
from typing import Any

from pgr_assets.models.faces import FACE_FUNCTIONS, FACE_SCRIPT, Faces
from pgr_assets.models.format import (
    AnimDataRow,
    EventDispatch,
    EventRow,
    EventTablesRow,
)
from pgr_assets.models.prefab import Prefab
from pgr_assets.models.tables import Tables
from pgr_assets.models.unity import read_tree

logger = logging.getLogger("pgr-assets")

DIGITS = 5
BLEND_DIGITS = 4
SYNC_SCRIPT = "XBoneTransformSync"
EVENT_TYPE_BUNDLE = "assets/temp/bytes/share/fight/npc/npcanimationevent.ab"
EVENT_TYPE_TABLE = "animationeventtype.tab.bytes"
STOP_FUNCTION = "OnFootType"
SOUND_SCRIPT = "XAnimationSound"
# Their ints index XAnimationSound's cue list, which ships nowhere.
SOUND_FUNCTIONS = frozenset({"PlaySoundOneShot", "PlaySoundByCueId", "PlayCv"})


@dataclass(frozen=True)
class Event:
    time: float
    function: str
    int_parameter: int
    float_parameter: float
    face: int | None = None

    def as_dict(self) -> EventRow:
        row: EventRow = {
            "time": self.time,
            "function": self.function,
            "int": self.int_parameter,
            "float": self.float_parameter,
        }
        if self.face is not None:
            row["face"] = self.face
        return row


def read_events(clip: Any, faces: Faces | None = None) -> list[Event]:
    events: list[Event] = []
    for raw in clip.m_Events:
        function = raw.functionName
        if function in SOUND_FUNCTIONS:
            continue
        face = None
        if function in FACE_FUNCTIONS:
            if faces is None:
                logger.debug(
                    f"{clip.m_Name}: {function} on a model with no face"
                    " binding, event dropped"
                )
                continue
            face = faces.resolve_slot(raw, clip.m_Name)
            if face is None:
                continue
        elif raw.data or raw.messageOptions or raw.objectReferenceParameter.m_PathID:
            logger.warning(
                f"{clip.m_Name}: event {function} carries a parameter"
                " the export drops"
            )
        events.append(
            Event(
                round(float(raw.time), DIGITS),
                function,
                int(raw.intParameter),
                round(float(raw.floatParameter), DIGITS),
                face,
            )
        )
    return events


@dataclass(frozen=True)
class AnimData:
    id: int
    layer: int
    state: str
    blend_time: float
    node: int | None

    def as_dict(self) -> AnimDataRow:
        return {
            "id": self.id,
            "layer": self.layer,
            "state": self.state,
            "blendTime": self.blend_time,
            "node": self.node,
        }


@dataclass
class EventTables:
    anim_data: list[AnimData] = field(default_factory=list)
    stop_anim_names: tuple[str, ...] = ()
    state_sync: bool = False
    state_sync_by_layer: bool = False

    def as_dict(self) -> EventTablesRow:
        row: EventTablesRow = {
            "stopAnimNames": list(self.stop_anim_names),
            "stateSync": self.state_sync,
            "stateSyncByLayer": self.state_sync_by_layer,
        }
        if self.anim_data:
            row["animData"] = [data.as_dict() for data in self.anim_data]
        return row


def read_event_tables(prefab: Prefab, stop_anim_names: tuple[str, ...]) -> EventTables:
    tables = EventTables(stop_anim_names=stop_anim_names)
    sounds = prefab.find_components(SOUND_SCRIPT)
    if not sounds:
        return tables
    component = sounds[0].component

    def parse(tree: dict) -> EventTables:
        return EventTables(
            anim_data=[
                AnimData(
                    int(raw["Id"]),
                    int(raw["Layer"]),
                    str(raw["StateName"]),
                    round(float(raw["BlendTime"]), BLEND_DIGITS),
                    prefab.resolve_node(component, raw["Transform"]),
                )
                for raw in tree["AnimDatas"]
            ],
            stop_anim_names=stop_anim_names,
            state_sync=bool(tree["SubNodeAnimEqualLength"]),
            state_sync_by_layer=bool(tree["SubNodeAnimLayerEqualLength"]),
        )

    read = read_tree(component, prefab.name, SOUND_SCRIPT, parse)
    if read is None:
        return tables
    unresolved = sum(1 for row in read.anim_data if row.node is None)
    if unresolved:
        logger.warning(
            f"{prefab.name}: {unresolved} of {len(read.anim_data)}"
            f" AnimDatas mounts are off the prefab"
        )
    return read


def load_stop_anim_names(tables: Tables) -> tuple[str, ...]:
    for function, params in tables.read(
        EVENT_TYPE_BUNDLE, EVENT_TYPE_TABLE, ("Function", "Params")
    ):
        if function == STOP_FUNCTION:
            return tuple(str(p) for p in (params or ()) if p)
    logger.warning(f"{EVENT_TYPE_TABLE}: no {STOP_FUNCTION} row")
    return ()


def read_bone_sync(prefab: Prefab) -> int | None:
    """
    XBoneTransformSync's bone name suffix length, if the prefab carries one.
    """
    for node, _, component in prefab.find_components(SYNC_SCRIPT):
        length = read_tree(
            component,
            prefab.name,
            SYNC_SCRIPT,
            lambda tree: int(tree["BoneNameSuffixLength"]),
        )
        if length is None:
            return None
        if node != 0:
            logger.warning(
                f"{prefab.name}: {SYNC_SCRIPT} on {prefab.nodes[node].name},"
                " not the root"
            )
        return length
    return None


def resolve_event_dispatch(prefab: Prefab) -> EventDispatch:
    """
    Fight loading moves clip events to XAnimationSound's integer frame windows.
    Chibis retain Unity's dispatch and are identified by XFaceAnimation.
    """
    if prefab.find_components(FACE_SCRIPT):
        return "native"
    return "frames"
