import logging
from collections import Counter
from collections.abc import Iterable

from pgr_assets.models.clips import (
    ClipAsset,
    ClipEntry,
    ClipInventory,
    resolve_source_stem,
)
from pgr_assets.models.model import Model
from pgr_assets.models.scene import Scene
from pgr_assets.models.texture import sum_encoded_bytes

logger = logging.getLogger("pgr-assets")


def report_model(model: Model) -> None:
    scene, playback = model.scene, model.playback
    if not scene.parts:
        logger.info("  glb: no meshes survived, manifest only")
    else:
        morphs = sum(len(part.geometry.morphs) for part in scene.parts)
        logger.info(
            f"  glb: {len(scene.nodes)} nodes, {len(scene.parts)} meshes,"
            f" {len(scene.skins)} skins, {len(scene.textures)} textures,"
            f" {morphs} morph targets"
        )
    skins = scene.skins
    bones = {joint for skin in skins for joint in skin.joints}
    logger.info(
        f"  rig: {len(skins)} skinned of {len(scene.parts)} meshes,"
        f" {sum(len(s.joints) for s in skins)} joints over {len(bones)} bones,"
        f" {sum(len(s.unresolved) for s in skins)} unresolved"
    )
    rigid = sum(1 for part in scene.parts if part.geometry.rigid)
    if rigid:
        logger.info(f"  rig: {rigid} meshes rigidly bound, one bone per vertex")
    _report_surfaces(scene)
    _report_clips(model.clips, scene)
    if scene.object_tags:
        nodes = {node for tag in scene.object_tags for node in tag.nodes}
        logger.info(
            f"  tags: {len(scene.object_tags)} object tags over {len(nodes)} nodes"
        )
    if scene.springs:
        logger.info(
            f"  springs: {len(scene.springs.chains)} chains,"
            f" {len(scene.springs.colliders)} colliders,"
            f" {len(scene.springs.presets)} presets"
        )
    tables = playback.event_tables
    if tables is not None and tables.anim_data:
        logger.info(f"  events: {len(tables.anim_data)} weapon states")
    if playback.bone_sync is not None:
        logger.info(f"  bone sync: suffix {playback.bone_sync}")


def _report_clips(clips: ClipInventory, scene: Scene) -> None:
    if not clips.entries:
        return

    logger.info(
        f"  clips: {len(clips.entries)} entries over {len(clips.assets)} assets,"
        f" {_describe_share(clips.assets, with_total=True)}"
    )

    by_layer: dict[int, list[ClipEntry]] = {}
    bare: dict[str, list[ClipEntry]] = {}
    for entry in clips.entries:
        if entry.layer is None:
            bare.setdefault(entry.source, []).append(entry)
        else:
            by_layer.setdefault(entry.layer, []).append(entry)

    for index, layer in enumerate(clips.layers):
        mask = ", masked" if layer.masked else ""
        _report_group(
            clips,
            f"layer {resolve_source_stem(layer.source)}/{layer.name}"
            f" {layer.blending} w={layer.weight:g}{mask}",
            by_layer.get(index, []),
        )
    for source, entries in bare.items():
        _report_group(clips, f"clip {resolve_source_stem(source)}", entries)

    types: Counter[int] = Counter()
    attributes: Counter[int] = Counter()
    for asset in clips.assets:
        types.update(asset.coverage.by_type)
        attributes.update(asset.coverage.by_attribute)
    logger.info(f"  binding: typeID {dict(sorted(types.items()))}")
    logger.info(f"  binding: transform attributes {dict(sorted(attributes.items()))}")

    written = [asset.file for asset in clips.assets if asset.file is not None]
    if written:
        described = sum(
            1 for e in clips.entries if clips.assets[e.asset].file is not None
        )
        raw = sum(f.bytes for f in written)
        stored = sum(f.stored_bytes for f in written)
        saving = (
            f", {stored / 1e6:.1f} MB stored ({raw / stored:.1f}x)"
            if 0 < stored < raw
            else ""
        )
        logger.info(
            f"  anim: {len(written)} files for {described} entries,"
            f" {raw / 1e6:.1f} MB,"
            f" {sum(f.tracks for f in written)} tracks,"
            f" {sum(f.morph_tracks for f in written)} morph tracks{saving}"
        )
        events = sum(f.events for f in written)
        if events:
            logger.info(
                f"  anim: {events} events on"
                f" {sum(1 for f in written if f.events)} clips"
            )
    if clips.unmatched:
        logger.info(f"  anim: {clips.unmatched} influence curves name a missing shape")


def _describe_share(assets: Iterable[ClipAsset], with_total: bool = False) -> str:
    total = resolved = 0
    for asset in assets:
        total += asset.coverage.transforms
        resolved += asset.coverage.resolved
    if not total:
        return "no transform bindings"
    # Groups share assets, so their totals do not sum to the header's.
    scale = f" of {total}" if with_total else ""
    return f"{resolved / total:.1%}{scale} transform bindings resolve"


def _report_group(clips: ClipInventory, label: str, entries: list[ClipEntry]) -> None:
    assets = {entry.asset for entry in entries}
    share = _describe_share(clips.assets[a] for a in assets)
    logger.info(f"  {label}: {len(entries)} entries, {share}")


def _report_surfaces(scene: Scene) -> None:
    shaders = Counter(part.materials.main.base_shader for part in scene.parts)
    for shader, count in sorted(shaders.items()):
        logger.info(f"  material: {shader or '<unreadable>'} x{count}")

    textures = scene.textures.values()
    lossy = sum(1 for texture in textures if not texture.lossless)
    normals = sum(1 for texture in textures if texture.normal)
    logger.info(
        f"  texture: {len(scene.textures)} distinct, {lossy} lossy,"
        f" {normals} AG-decoded, {sum_encoded_bytes(scene.textures) / 1e6:.1f} MB encoded"
    )

    alternates = scene.alternates
    if alternates:
        eyes = sum(len(fade.eyes) for fade in alternates.hair)
        masks = sum(
            eye.texture is not None for fade in alternates.hair for eye in fade.eyes
        )
        entries = sum(len(swap.entries) for swap in alternates.parts)
        logger.info(
            f"  alternate: {len(alternates.parts)} part swaps over {entries} renderers,"
            f" {len(alternates.hair)} hair fades, {eyes} eyes ({masks} masked)"
        )
