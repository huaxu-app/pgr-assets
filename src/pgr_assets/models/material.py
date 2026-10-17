import logging
from dataclasses import dataclass, field, replace
from typing import Any

from pgr_assets.models.emission import FLOW_SLOT, EmissionFlow
from pgr_assets.models.format import Family
from pgr_assets.models.library import CubemapLibrary
from pgr_assets.models.mesh import Uv3Layout
from pgr_assets.models.render import Render, resolve_render
from pgr_assets.models.shader import (
    COLOR_TYPE,
    FLOAT_TYPES,
    VARIANT_MARKER,
    VECTOR_TYPE,
    ShaderInfo,
    State,
    read_shader,
)
from pgr_assets.models.texture import TextureSet
from pgr_assets.models.unity import read_pointer, resolve_asset_key

logger = logging.getLogger("pgr-assets")


# Game shader, `Variant/` stripped, to its family.
FAMILIES: dict[str, Family] = {
    "XCharacter/Character": "character",
    "XCharacter/EffectCharacter": "effectCharacter",
    "XCharacter/Character_UnderWater": "underwater",
    "XCharacter/Outline": "outline",
    "XCharacter/CharacterSparkle": "sparkle",
    "XTransparentBloomModify": "bloom",
    "XEffect/Effect": "effect",
    "XEffect/EffectNoBatching": "effect",
    "XEffect/EffectShield": "effectShield",
    "XScene/XScenePBR": "scenePbr",
    "XScene/StandardSimple": "standardSimple",
    "XFur": "fur",
    "XShadowVolume/StencilVolumeFrontBack": "shadowVolume",
}

AUXILIARY = {"outline", "sparkle", "bloom"}

# Stencil extrusion geometry. Bound to no textures, sitting alone on dedicated
# *MeshShadowVolume renderers, and a viewer draws it as a solid blob.
SKIP_RENDERER = {"shadowVolume"}

# Surface shaders that lose to nothing. 31 renderers carry two non-auxiliary
# materials and 15 order them the wrong way round, so position alone picks an
# additive overlay half the time.
CHARACTER_FAMILY = {"character", "effectCharacter"}

UV3_IS_A_UV = {"scenePbr"}

# Slots whose UV set is not the mesh's first.
UV2_SLOTS = {"_FaceMap", "_DetailMap"}

CUBEMAP_SLOT = "_CubeMap"

# The keyword's number is no guide: _MASK_UV2 and _MASKUV1 both read Unity uv1,
# _MASKUV3 reads uv2. Each entry is read off the programs.
KEYWORD_UV_SLOTS = {
    ("_MaskTex", "_MASK_UV2"): 1,
    ("_MaskTex", "_MASKUV1"): 1,
    ("_Effect_MaskTex", "_MASKUV3"): 2,
    ("_CharacterDissolutionTex", "_CHARACTER_DISSOLUTION_UV3"): 2,
}
# EffectCharacter picks this one with a float, 0 1 2 for Unity uv0 uv1 uv2.
FLOAT_UV_SLOTS = {"_VertexOffset_Tex": "_VertexOffset_UVSelect"}
VERTEX_COLOR_KEYWORDS = {
    "_VERTEX_COLOR",
    "_SKIN_VERTEX_COLOR",
    "_OUTLINE_VERTEX_COLOR",
    "_MULTI_OUTLINE_COLOR",
}
# Effect reads vertex color with no keyword at all, until both of these turn it off.
EFFECT_COLOR_OFF = {"_VERTEX_RGB_OFF", "_VERTEX_ALPHA_OFF"}
# Programs that read uv1.zw as zone ids.
ZONE_KEYWORDS = ("_MUTLI_CHANEL_SKIN", "_MUTLI_CHANEL_SHADOW_COLOR")


@dataclass(frozen=True)
class TextureRef:
    slot: str
    key: str
    # The Unity UV channel the shader samples this slot with.
    source_uv: int
    scale: tuple[float, float]
    offset: tuple[float, float]


@dataclass(frozen=True)
class Surface:
    name: str
    base_shader: str
    # The Unity material's identity, so a swap back to the renderer's own reads as one.
    key: str = ""
    keywords: list[str] = field(default_factory=list)
    tags: dict[str, str] = field(default_factory=dict)
    floats: dict[str, float] = field(default_factory=dict)
    colors: dict[str, list[float]] = field(default_factory=dict)
    vectors: dict[str, list[float]] = field(default_factory=dict)
    textures: list[TextureRef] = field(default_factory=list)
    cubemap: str | None = None
    custom_render_queue: int = -1
    emission_flow: EmissionFlow | None = None
    state: State = field(default_factory=dict)

    @property
    def dqs(self) -> bool:
        return "_GPU_DQS" in self.keywords

    @property
    def family(self) -> Family | None:
        return FAMILIES.get(self.base_shader.removeprefix("Variant/"))

    @property
    def reads_color(self) -> bool:
        if self.family == "effect":
            return not EFFECT_COLOR_OFF.issubset(self.keywords)
        return not VERTEX_COLOR_KEYWORDS.isdisjoint(self.keywords)


@dataclass(frozen=True)
class MaterialSet:
    """
    One Unity material and its render state. Every other material on the renderer
    draws the same geometry as a pass of its own.
    """

    main: Surface
    render: Render
    passes: list["MaterialSet"] = field(default_factory=list)

    @property
    def surfaces(self) -> list[Surface]:
        return [self.main, *(materials.main for materials in self.passes)]


def bind_emission_flow(surface: Surface, flow: EmissionFlow) -> Surface:
    """
    The controller overwrites all four ST components, so the authored binding goes.
    """
    scale, offset = flow.resting_st
    return replace(
        surface,
        emission_flow=flow,
        textures=[
            replace(reference, scale=scale, offset=offset)
            if reference.slot == FLOW_SLOT
            else reference
            for reference in surface.textures
        ],
    )


def read_materials(
    renderer: Any,
    textures: TextureSet,
    cubemaps: CubemapLibrary,
    where: str,
    flow: EmissionFlow | None = None,
) -> MaterialSet | None:
    """
    Read every material on a renderer and select the one that gets emitted.
    """
    surfaces = [
        surface
        for surface in (
            read_surface(pointer, textures, cubemaps, where)
            for pointer in renderer.m_Materials or ()
        )
        if surface is not None
    ]
    if not surfaces:
        logger.warning(f"{where}: renderer has no readable material")
        return None

    if any(surface.family in SKIP_RENDERER for surface in surfaces):
        return None

    main = _select_main(surfaces)
    if main is None:
        logger.debug(f"{where}: only auxiliary materials, nothing to draw")
        return None

    passes = [_finish_set(s, [], where) for s in surfaces if s is not main]
    if flow is not None:
        main = bind_emission_flow(main, flow)
    return _finish_set(main, passes, where)


def _select_main(surfaces: list[Surface]) -> Surface | None:
    """
    The first non-auxiliary surface, except that a character surface always wins.
    """
    candidates = [s for s in surfaces if s.family not in AUXILIARY]
    if not candidates:
        return None

    preferred = next((s for s in candidates if s.family in CHARACTER_FAMILY), None)
    return preferred or candidates[0]


def read_material_set(
    pointer: Any, textures: TextureSet, cubemaps: CubemapLibrary, where: str
) -> MaterialSet | None:
    surface = read_surface(pointer, textures, cubemaps, where)
    if surface is None:
        return None
    return _finish_set(surface, [], where)


def resolve_uv3_layout(materials: MaterialSet) -> Uv3Layout:
    """
    Whether this renderer's uv3 is the outline's smooth normal rather than a UV set.
    """
    if materials.main.family in UV3_IS_A_UV:
        return Uv3Layout.TEXCOORD
    if materials.main.family in CHARACTER_FAMILY:
        return Uv3Layout.SMOOTH_NORMAL
    if any(p.main.family == "outline" for p in materials.passes):
        return Uv3Layout.SMOOTH_NORMAL
    return Uv3Layout.TEXCOORD


def _finish_set(main: Surface, passes: list[MaterialSet], where: str) -> MaterialSet:
    if main.base_shader and main.family is None:
        logger.warning(f"{where}: unknown base shader {main.base_shader}")
    if main.dqs:
        logger.debug(f"{where}: dual quaternion skinning, emitted as linear blend")
    return MaterialSet(main, resolve_render(main), passes)


def read_surface(
    pointer: Any, textures: TextureSet, cubemaps: CubemapLibrary, where: str
) -> Surface | None:
    material = read_pointer(pointer, where, "material")
    if material is None:
        return None

    info = ShaderInfo()
    try:
        info = read_shader(material.m_Shader)
    except Exception as error:  # noqa: BLE001  23 of 12254 shader pointers are authored null
        logger.warning(
            f"{where}: {material.m_Name} has no readable shader,"
            f" {type(error).__name__}: {error}"
        )

    keywords = list(info.keywords)
    # Without a variant name to carry the keywords, the material does.
    if VARIANT_MARKER not in info.variant:
        keywords = [str(k) for k in material.m_ValidKeywords or ()]

    # Unity only saves what someone touched in the inspector, the shader's declared
    # defaults are the rest. Effect declares _ZWrite 0, so this isn't cosmetic.
    properties = material.m_SavedProperties
    declared = info.declared
    floats = {name: value[0] for name, (kind, value) in declared.items() if kind in FLOAT_TYPES}
    floats |= {_read_name(k): float(v) for k, v in properties.m_Floats or ()}
    # m_Colors holds Vectors too. Only Colors are authored sRGB, so the shader's
    # declared type splits them. An undeclared save stays a color.
    colors = {name: list(value) for name, (kind, value) in declared.items() if kind == COLOR_TYPE}
    vectors = {name: list(value) for name, (kind, value) in declared.items() if kind == VECTOR_TYPE}
    for raw, color in properties.m_Colors or ():
        name = _read_name(raw)
        block = vectors if declared.get(name, (COLOR_TYPE,))[0] == VECTOR_TYPE else colors
        block[name] = [color.r, color.g, color.b, color.a]
    refs, cubemap = _read_textures(
        properties, keywords, floats, textures, cubemaps, where
    )
    # The shader's dicts are cached for the run, so every surface gets its own.
    return Surface(
        name=material.m_Name,
        base_shader=info.base,
        key=resolve_asset_key(material),
        keywords=keywords,
        tags=dict(info.tags),
        floats=floats,
        colors=colors,
        vectors=vectors,
        textures=refs,
        cubemap=cubemap,
        custom_render_queue=int(material.m_CustomRenderQueue),
        state=dict(info.state),
    )


def _read_textures(
    properties: Any,
    keywords: list[str],
    floats: dict[str, float],
    textures: TextureSet,
    cubemaps: CubemapLibrary,
    where: str,
) -> tuple[list[TextureRef], str | None]:
    refs = []
    cubemap = None
    for name, env in properties.m_TexEnvs or ():
        slot = _read_name(name)
        if slot == CUBEMAP_SLOT:
            cubemap = cubemaps.add(env.m_Texture, where)
            continue

        key = textures.add(env.m_Texture, slot, where)
        if key is None:
            continue
        refs.append(
            TextureRef(
                slot=slot,
                key=key,
                source_uv=_resolve_source_uv(keywords, floats, slot),
                scale=(env.m_Scale.x, env.m_Scale.y),
                offset=(env.m_Offset.x, env.m_Offset.y),
            )
        )
    return refs, cubemap


def _resolve_source_uv(keywords: list[str], floats: dict[str, float], slot: str) -> int:
    if slot in UV2_SLOTS:
        return 1
    if slot in FLOAT_UV_SLOTS:
        select = floats.get(FLOAT_UV_SLOTS[slot], 0.0)
        return 2 if select > 1.5 else 1 if select > 0.5 else 0
    for (keyed_slot, keyword), uv in KEYWORD_UV_SLOTS.items():
        if slot == keyed_slot and keyword in keywords:
            return uv
    return 0


def _read_name(name: Any) -> str:
    return name if isinstance(name, str) else name.name
