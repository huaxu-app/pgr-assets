"""
One built target, as its three writers consume it.
"""

from dataclasses import dataclass, field

from pgr_assets.models.clips import ClipInventory
from pgr_assets.models.context import Context
from pgr_assets.models.events import EventTables
from pgr_assets.models.format import EventDispatch
from pgr_assets.models.scene import Scene
from pgr_assets.models.skills import StateSkills
from pgr_assets.models.transitions import Transitions


@dataclass
class Playback:
    contexts: list[Context]
    event_tables: EventTables | None = None
    event_dispatch: EventDispatch = "frames"
    bone_sync: int | None = None
    transitions: Transitions | None = None
    character: int | None = None
    skills: StateSkills = field(default_factory=dict)


@dataclass
class Model:
    scene: Scene
    clips: ClipInventory
    playback: Playback
