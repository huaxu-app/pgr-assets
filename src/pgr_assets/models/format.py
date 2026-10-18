"""
The output contract: file names, the tree they sit in, and every row as a TypedDict.

    _shared/cubemaps/           <name>.webp per cubemap plus an index.json of them
    <asset id>/base.glb
    <asset id>/manifest.json
    <asset id>/anim/[<layer>/]<clip>.json
    <asset id>/.build.json      the marker

A target builds into <dir>.building and swaps in by rename, parking the last build as
<dir>.old until the new one lands. The marker goes in last, so a target without one
never finished. Its key hashes the sha1 of every bundle the build read, and it records
the brotli quality the target sits at.

Above quality 0 the glb and every json but the marker exist only as <name>.br, the
webp files stay as they are. Paths in the output never name .br, the file server
serves the sibling.

A cubemap keeps its authored name until a different asset claims it, then the
newcomer gets a hash of its asset key tacked on.
"""

import os
from typing import Any, Literal, NotRequired, TypedDict, cast

FORMAT_VERSION = 1
CLIP_VERSION = 1

MODEL_FILE = "base.glb"
MANIFEST_FILE = "manifest.json"
ANIM_DIR = "anim"
INDEX_FILE = "index.json"
BUILD_FILE = ".build.json"
CUBEMAP_DIR = os.path.join("_shared", "cubemaps")
STAGING_SUFFIX = ".building"
OLD_SUFFIX = ".old"
BROTLI_SUFFIX = ".br"
ROLE_PREFIX = "assets/product/role/"


def resolve_asset_id(path: str) -> str:
    """
    The asset's own path, lowercased, minus the shared prefix and the extension.
    """
    return os.path.splitext(path.lower().removeprefix(ROLE_PREFIX))[0]


def resolve_target_dir(output: str, model_path: str) -> str:
    return os.path.join(output, *resolve_asset_id(model_path).split("/"))


def round5(value: float) -> float:
    # + 0.0 folds -0.0, which JSON would print as is.
    return round(value, 5) + 0.0


Vec3 = list[float]
Curve = list[list[float]]

Blending = Literal["override", "additive"]
ColliderKind = Literal["sphere", "capsule", "plane"]
ColliderBound = Literal["inside", "outside"]
CubemapEncoding = Literal["RGBM6", "LDR6"]
Cull = Literal["none", "front", "back"]
ZTest = Literal[
    "always", "never", "less", "equal", "lequal", "greater", "notequal", "gequal"
]
Family = Literal[
    "character",
    "effectCharacter",
    "underwater",
    "outline",
    "sparkle",
    "bloom",
    "effect",
    "effectShield",
    "scenePbr",
    "standardSimple",
    "fur",
    "shadowVolume",
]


# manifest.json


class StateRow(TypedDict):
    clip: int
    # A blend tree's children in tree order. `clip` is the dominant one.
    blend: NotRequired[list[int]]
    speed: NotRequired[float]
    cycleOffset: NotRequired[float]
    mirror: NotRequired[bool]
    skills: NotRequired[list[int]]
    # Entering the state sets this face slot, else it resets to the material's.
    face: NotRequired[int]
    faceLock: NotRequired[bool]
    faceKeep: NotRequired[bool]


class LayerRow(TypedDict):
    name: str
    blending: Blending
    default: str | None
    mask: NotRequired[list[int]]
    states: dict[str, StateRow]


class ControllerRow(TypedDict):
    id: str
    layers: list[LayerRow]


class ClipRow(TypedDict):
    name: str
    file: str
    duration: float
    frameRate: float
    loop: bool
    rootNode: int | None


class StateRef(TypedDict):
    controller: str
    layer: int
    state: str


class ClipRef(TypedDict):
    clip: int


class MountRow(TypedDict):
    slot: int
    name: str
    node: int
    skillNode: int | None


class PartNpcRow(TypedDict):
    target: str
    node: int


class TransitionsRow(TypedDict):
    default: float
    # By layer index. "*" is any state. Look up [from][to], then ["*"][to], then default.
    layers: list[dict[str, dict[str, float]]]


class ContextRow(TypedDict):
    base: str | None
    levels: NotRequired[list[str]]
    entry: StateRef | ClipRef | None
    idle: StateRef | ClipRef | None
    hiddenNodes: NotRequired[list[int]]
    mounts: NotRequired[list[MountRow]]
    partNpcs: NotRequired[list[PartNpcRow]]
    rotation: NotRequired[list[float]]
    transitions: NotRequired[TransitionsRow]


class EventRow(TypedDict):
    time: float
    function: str
    face: NotRequired[int]
    int: int
    float: float


class AnimDataRow(TypedDict):
    id: int
    layer: int
    state: str
    blendTime: float
    node: int | None


class EventTablesRow(TypedDict):
    animData: NotRequired[list[AnimDataRow]]
    stopAnimNames: list[str]
    stateSync: bool
    stateSyncByLayer: bool


class BoneSyncRow(TypedDict):
    suffixLength: int


EventDispatch = Literal["native", "frames"]


class ManifestDoc(TypedDict):
    formatVersion: int
    target: str
    model: str | None
    modelStoredBytes: NotRequired[int]
    characterId: NotRequired[int]
    eventDispatch: EventDispatch
    controllers: list[ControllerRow]
    clips: list[ClipRow]
    contexts: dict[str, ContextRow]
    eventTables: NotRequired[EventTablesRow]
    boneSync: NotRequired[BoneSyncRow]


# .build.json, the marker that makes a target directory complete


class MarkerDoc(TypedDict):
    key: str
    quality: int
    bundles: list[str]
    cubemaps: list[str]
    textures: NotRequired[str]


# anim/<layer>/<clip>.json. Tracks address glb nodes by index. Animated tracks are
# packed against packing.times, a constant track ships its one value.


class ConstantRow(TypedDict):
    node: int
    property: str
    target: NotRequired[int]
    value: list[float]


class DroppedRow(TypedDict):
    at: int
    component: int


class PackedRotationRow(TypedDict):
    node: int
    property: str
    # Three components per key, scaled by (2^(rotationBits-1) - 1) / sqrt(1/2).
    deltas: list[int]
    # The component left out from key `at` on. The dropped value is positive.
    dropped: list[DroppedRow]


class PackedValueRow(TypedDict):
    node: int
    property: str
    target: NotRequired[int]
    # value = step / 10^valueDigits
    deltas: list[int]


class Packing(TypedDict):
    times: list[float]
    rotationBits: int
    valueDigits: int


class ClipDoc(TypedDict):
    version: int
    tracks: list[ConstantRow | PackedRotationRow | PackedValueRow]
    packing: NotRequired[Packing]
    events: NotRequired[list[EventRow]]


# base.glb extras


class NodeExtras(TypedDict):
    projectionShadowAlpha: NotRequired[int]
    castsShadow: NotRequired[bool]
    receivesShadow: NotRequired[bool]
    castsProjectionShadow: NotRequired[bool]


class MeshExtras(TypedDict):
    targetNames: list[str]


class AnchorsRow(TypedDict):
    head: int | None
    body: int | None


class ObjectTagRow(TypedDict):
    name: str
    nodes: list[int]


class SpringPresetRow(TypedDict):
    name: str
    damping: float
    elasticity: float
    stiffness: float
    inert: float
    weight: float
    gravity: Vec3
    force: Vec3
    freezeAxis: int
    dampingCurve: NotRequired[Curve]
    elasticityCurve: NotRequired[Curve]
    stiffnessCurve: NotRequired[Curve]
    inertCurve: NotRequired[Curve]


class SpringColliderRow(TypedDict):
    node: int
    kind: ColliderKind
    bound: ColliderBound
    # Node space, glTF basis. A sphere's center, a point on a plane.
    center: NotRequired[Vec3]
    ends: NotRequired[list[Vec3]]
    normal: NotRequired[Vec3]
    radius: NotRequired[float]


class SpringChainRow(TypedDict):
    node: int
    root: int
    preset: int
    radius: float
    colliders: NotRequired[list[int]]
    exclusions: NotRequired[list[int]]
    endLength: NotRequired[float]
    endOffset: NotRequired[Vec3]
    radiusCurve: NotRequired[Curve]
    maxWindForce: NotRequired[float]
    windCurve: NotRequired[Curve]
    maxWindCurve: NotRequired[Curve]


class SpringsRow(TypedDict):
    presets: list[SpringPresetRow]
    colliders: NotRequired[list[SpringColliderRow]]
    chains: list[SpringChainRow]


class SelfShadowRow(TypedDict):
    pitch: float
    yawOffset: float


class AlternateEntryRow(TypedDict):
    node: int
    hide: bool
    material: NotRequired[int]


class PartSwapRow(TypedDict):
    partId: int
    entries: list[AlternateEntryRow]


class EyeRow(TypedDict):
    node: int
    mask: int | None


class AdditionalRow(TypedDict):
    node: int
    material: int


class HairFadeRow(TypedDict):
    node: int
    material: int
    fadeDistance: float
    eyes: list[EyeRow]
    set: NotRequired[str]
    checkNode: int | None
    eyeAlphaBlending: NotRequired[bool]
    additional: NotRequired[AdditionalRow]


class AlternatesRow(TypedDict):
    parts: NotRequired[list[PartSwapRow]]
    hairFade: NotRequired[list[HairFadeRow]]
    initial: NotRequired[int]


class FacesRow(TypedDict):
    node: int
    textures: list[int]


class SceneExtras(TypedDict):
    formatVersion: int
    anchors: AnchorsRow
    objectTags: NotRequired[list[ObjectTagRow]]
    alternates: NotRequired[AlternatesRow]
    springBones: NotRequired[SpringsRow]
    selfShadow: NotRequired[SelfShadowRow]
    faces: NotRequired[FacesRow]


class BlendRow(TypedDict):
    src: str
    dst: str


class RenderRow(TypedDict):
    blend: BlendRow | None
    colorMask: str
    depthWrite: bool
    zTest: ZTest
    alphaTest: float
    cull: Cull
    reversedWinding: bool
    renderOrder: int


class TextureBindingRow(TypedDict):
    index: int
    texCoord: int
    scale: list[float]
    offset: list[float]


class EmissionFlowRow(TypedDict):
    speed: float
    startFlow: float
    extendedRange: int
    useAnimation: bool
    curve: Curve


class SurfaceRow(TypedDict):
    base: str
    keywords: list[str]
    textures: dict[str, TextureBindingRow]
    floats: dict[str, float]
    colors: dict[str, list[float]]
    vectors: dict[str, list[float]]
    cubemap: NotRequired[str]
    emissionFlow: NotRequired[EmissionFlowRow]


class MaterialExtras(TypedDict):
    family: Family | None
    render: RenderRow
    shader: SurfaceRow
    passes: NotRequired[list[int]]


class TextureExtras(TypedDict):
    colorSpace: str


Extras = NodeExtras | MeshExtras | SceneExtras | MaterialExtras | TextureExtras


def to_plain(row: Extras | None) -> dict[str, Any] | None:
    """
    pygltflib types extras as a plain dict, which a TypedDict is not.
    """
    return cast(dict[str, Any] | None, row)


# _shared/cubemaps/index.json


class CubemapRow(TypedDict):
    name: str
    key: str
    faceSize: int
    mips: int
    encoding: CubemapEncoding
    colorSpace: str


class CubemapIndex(TypedDict):
    formatVersion: int
    cubemaps: dict[str, CubemapRow]
