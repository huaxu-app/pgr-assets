"""
What a material needs from its shader: the base name and variant keywords, the
declared property defaults, and pass 0's fixed-function state.
"""

from dataclasses import dataclass, field
from typing import Any

from pgr_assets.models.unity import resolve_reader_key

# SerializedPropertyType. No shader declares an Int (5), UnityPy doesn't even
# name it, so it rides along as a float in case one ever shows up.
COLOR_TYPE = 0
VECTOR_TYPE = 1
FLOAT_TYPES = {2, 3, 5}
TEXTURE_TYPE = 4

Declared = dict[str, tuple[int, list[float]]]

# Pass state: the property it's bound to, or None and the literal.
State = dict[str, tuple[str | None, float]]

UNBOUND = {"", "<noninit>"}

# Splits a variant shader name into its base and the keywords it was compiled with.
VARIANT_MARKER = "-Variant-"
QUEUE_TAG = "QUEUE"


@dataclass
class ShaderInfo:
    """
    What a material needs from its shader, plain data so the cache pins nothing.
    """

    base: str = ""
    variant: str = ""
    keywords: list[str] = field(default_factory=list)
    tags: dict[str, str] = field(default_factory=dict)
    declared: Declared = field(default_factory=dict)
    state: State = field(default_factory=dict)


# One process is one run, and targets share shaders like crazy, so it never clears.
_shaders: dict[str, ShaderInfo] = {}


def parse_shader_name(shader: Any) -> tuple[str, str, list[str]]:
    parsed = shader.m_ParsedForm
    variant = parsed.m_Name if parsed is not None else ""
    if not variant:
        return "", "", []

    base, _, tail = variant.partition(VARIANT_MARKER)
    base = base.removesuffix("-Variant")
    keywords = [token for token in tail.split("-") if token.startswith("_")]
    return base, variant, keywords


def read_shader(pointer: Any) -> ShaderInfo:
    """
    Keyed on the pointer, so a cached shader is never parsed again.
    """
    key = resolve_reader_key(pointer.deref())
    cached = _shaders.get(key)
    if cached is not None:
        return cached

    shader = pointer.read()
    base, variant, keywords = parse_shader_name(shader)
    parsed = shader.m_ParsedForm
    subshader = _pick_main_subshader(parsed)
    info = ShaderInfo(
        base=base,
        variant=variant,
        keywords=keywords,
        tags={} if subshader is None else {k: v for k, v in subshader.m_Tags.tags or ()},
        declared=_read_declared(parsed),
        state={} if subshader is None or not subshader.m_Passes else _read_state(subshader.m_Passes[0]),
    )
    _shaders[key] = info
    return info


def _pick_main_subshader(parsed: Any) -> Any:
    """
    The first subshader carrying QUEUE, else the first.

    Taking the first tagged subshader would let one carrying only RenderType shadow
    a later one that answers the render order.
    """
    subshaders: list[Any] = [] if parsed is None else parsed.m_SubShaders
    tagged = (s for s in subshaders if any(k == QUEUE_TAG for k, _ in s.m_Tags.tags or ()))
    return next(tagged, subshaders[0] if subshaders else None)


def _read_declared(parsed: Any) -> Declared:
    """
    Every non-texture property the shader declares, with its default.
    """
    props = parsed.m_PropInfo.m_Props if parsed is not None else []
    textures = {prop.m_Name for prop in props if prop.m_Type == TEXTURE_TYPE}
    # A declared _MainTex_ST is fed from the _MainTex binding, its [1, 1, 0, 0]
    # default would be a second, wrong copy of the tiling.
    return {
        prop.m_Name: (
            prop.m_Type,
            [prop.m_DefValue_0_, prop.m_DefValue_1_, prop.m_DefValue_2_, prop.m_DefValue_3_],
        )
        for prop in props
        if prop.m_Type != TEXTURE_TYPE and prop.m_Name.removesuffix("_ST") not in textures
    }


def _read_state(shader_pass: Any) -> State:
    """
    Pass 0's fixed-function state. Pass 0 is the main draw on every shader we know,
    the rest are shadow casters, depth prepasses and mirror copies.
    """
    state = shader_pass.m_State
    blend = state.rtBlend0
    values = {
        "cull": state.culling,
        "zWrite": state.zWrite,
        "zTest": state.zTest,
        "src": blend.srcBlend,
        "dst": blend.destBlend,
        "mask": blend.colMask,
    }
    return {
        name: (None if value.name in UNBOUND else value.name, float(value.val))
        for name, value in values.items()
    }
