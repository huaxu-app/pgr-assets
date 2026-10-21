import logging
from collections.abc import Mapping
from dataclasses import dataclass

from pgr_assets.models.clips import ClipInventory
from pgr_assets.models.context import FIGHT_CONTEXT, Context, RestPolicy
from pgr_assets.models.faces import FaceMode
from pgr_assets.models.format import (
    FORMAT_VERSION,
    MODEL_FILE,
    ClipRef,
    ClipRow,
    ContextRow,
    ControllerRow,
    LayerRow,
    ManifestDoc,
    StateRef,
    StateRow,
    TransitionsRow,
    resolve_asset_id,
    round5,
)
from pgr_assets.models.model import Model

logger = logging.getLogger("pgr-assets")

IDLE_STATE = "Stand1"


def build_manifest(model: Model, target: str, model_stored: int | None) -> ManifestDoc:
    playback = model.playback
    transitions = playback.transitions
    described = describe_clips(model.clips, playback.skills)
    doc: ManifestDoc = {
        "formatVersion": FORMAT_VERSION,
        "target": target,
        "model": MODEL_FILE if model.scene.parts else None,
        "eventDispatch": playback.event_dispatch,
        "controllers": described.controllers,
        "clips": described.clips,
        "contexts": describe_contexts(
            playback.contexts,
            described,
            None if transitions is None else transitions.as_dict(),
        ),
    }
    if model_stored is not None:
        doc["modelStoredBytes"] = model_stored
    if playback.character is not None:
        doc["characterId"] = playback.character
    if playback.default_context is not None:
        doc["defaultContext"] = playback.default_context
    if playback.event_tables is not None:
        doc["eventTables"] = playback.event_tables.as_dict()
    if playback.bone_sync is not None:
        doc["boneSync"] = {"suffixLength": playback.bone_sync}
    return doc


@dataclass
class Described:
    controllers: list[ControllerRow]
    clips: list[ClipRow]
    # Clip index by source path, for the controller-less UI clip.
    bare: dict[str, int]
    # Per controller id and layer, the state the UI moves each state on to.
    ui_next: dict[str, list[dict[str, str]]]


def describe_clips(
    inventory: ClipInventory, skills: Mapping[str, tuple[int, ...]]
) -> Described:
    clips: list[ClipRow] = []
    clip_index: dict[int, int] = {}
    for asset_index, asset in enumerate(inventory.assets):
        written = asset.file
        if written is None:
            continue
        clip_index[asset_index] = len(clips)
        clips.append(
            {
                "name": asset.name,
                "file": written.path,
                "duration": written.duration,
                "frameRate": written.frame_rate,
                "loop": written.loop,
                "rootNode": written.root_node,
            }
        )

    controllers: dict[str, ControllerRow] = {}
    layer_rows: list[LayerRow] = []
    ui_next: dict[str, list[dict[str, str]]] = {}
    for layer in inventory.layers:
        row: LayerRow = {
            "name": layer.name,
            "blending": layer.blending,
            "default": layer.default_state,
            "states": {},
        }
        if layer.masked:
            row["mask"] = list(layer.mask)
        layer_rows.append(row)
        controllers.setdefault(
            layer.source, {"id": resolve_asset_id(layer.source), "layers": []}
        )["layers"].append(row)
        ui_next.setdefault(resolve_asset_id(layer.source), []).append(dict(layer.ui_next))

    bare: dict[str, int] = {}
    for entry in inventory.entries:
        if entry.asset not in clip_index:
            continue
        if entry.layer is None:
            bare[entry.source] = clip_index[entry.asset]
            continue
        state: StateRow = {"clip": clip_index[entry.asset]}
        if len(entry.children) > 1:
            state["blend"] = [clip_index[c] for c in entry.children if c in clip_index]
        timing = entry.timing
        if timing is not None:
            if timing.speed != 1.0:
                state["speed"] = timing.speed
            if timing.cycle_offset != 0.0:
                state["cycleOffset"] = timing.cycle_offset
            if timing.mirror:
                state["mirror"] = True
        if owners := skills.get(entry.name):
            state["skills"] = list(owners)
        face = entry.face
        if face is not None:
            if face.slot is not None:
                state["face"] = face.slot
            if face.mode is FaceMode.LOCK:
                state["faceLock"] = True
            if face.mode is FaceMode.KEEP:
                state["faceKeep"] = True
        states = layer_rows[entry.layer]["states"]
        if entry.name in states and states[entry.name] != state:
            logger.warning(f"{entry.source}: two states named {entry.name} in one layer")
        states[entry.name] = state

    return Described(list(controllers.values()), clips, bare, ui_next)


def walk_ui_chain(ui_next: Mapping[str, str], start: str) -> list[str]:
    walk = [start]
    while (step := ui_next.get(walk[-1])) is not None and step not in walk:
        walk.append(step)
    return walk


def describe_contexts(
    contexts: list[Context],
    described: Described,
    transitions: TransitionsRow | None,
) -> dict[str, ContextRow]:
    by_id = {controller["id"]: controller for controller in described.controllers}
    rows: dict[str, ContextRow] = {}
    for context in contexts:
        base = None if context.base is None else resolve_asset_id(context.base)
        clip = None if context.clip is None else described.bare.get(context.clip)
        entry: StateRef | ClipRef | None = None
        idle: StateRef | ClipRef | None = None
        if clip is not None:
            entry = idle = {"clip": clip}
        elif base is not None:
            layers = by_id[base]["layers"]
            index = next(
                (i for i, row in enumerate(layers) if row["name"] == context.start_layer),
                0,
            )
            states = layers[index]["states"]
            start = context.start_state or layers[index]["default"]
            rest = IDLE_STATE
            if start is not None and context.rest is RestPolicy.UI_CHAIN_END:
                # Rest where the chain ends, enter on the last one-shot before it.
                chain = walk_ui_chain(described.ui_next[base][index], start)
                walk = [state for state in chain if state in states]
                if walk:
                    start = walk[-2] if len(walk) > 2 else walk[0]
                    rest = walk[-1]
            if start is not None and start in states:
                entry = {"controller": base, "layer": index, "state": start}
            if context.rest is RestPolicy.ENTRY:
                idle = entry
            elif rest in states:
                idle = {"controller": base, "layer": index, "state": rest}

        row: ContextRow = {"base": base, "entry": entry, "idle": idle}
        if context.levels:
            row["levels"] = [resolve_asset_id(path) for path in context.levels]
        if context.hidden:
            row["hiddenNodes"] = list(context.hidden)
        if context.state_hidden:
            row["stateHides"] = {
                state: list(nodes) for state, nodes in context.state_hidden.items()
            }
        if context.mounts:
            row["mounts"] = [
                {"slot": m.slot, "name": m.name, "node": m.node, "skillNode": m.skill_node}
                for m in context.mounts
            ]
        if context.part_npcs:
            row["partNpcs"] = [{"target": p.target, "node": p.node} for p in context.part_npcs]
        if context.rotation is not None:
            row["rotation"] = [round5(value) for value in context.rotation]
        if context.name == FIGHT_CONTEXT and transitions is not None:
            row["transitions"] = transitions
        rows[context.name] = row
    return rows
