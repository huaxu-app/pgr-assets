"""
The draw state of a shader's main pass, resolved against the material that binds it.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from pgr_assets.models.format import Cull, RenderRow, ZTest
from pgr_assets.models.shader import QUEUE_TAG

if TYPE_CHECKING:
    from pgr_assets.models.material import Surface

logger = logging.getLogger("pgr-assets")


class Winding(Enum):
    AUTHORED = "authored"
    REVERSED = "reversed"

# Unity's CullMode, CompareFunction and BlendMode enums. ZTest 0 is "Disabled",
# which tests nothing, so always.
CULL: dict[int, Cull] = {0: "none", 1: "front", 2: "back"}
FLIPPED_CULL: dict[Cull, Cull] = {"none": "none", "front": "back", "back": "front"}
Z_TESTS: dict[int, ZTest] = {
    0: "always",
    1: "never",
    2: "less",
    3: "equal",
    4: "lequal",
    5: "greater",
    6: "notequal",
    7: "gequal",
    8: "always",
}
BLEND_FACTORS = {
    0: "zero",
    1: "one",
    2: "dstColor",
    3: "srcColor",
    4: "oneMinusDstColor",
    5: "srcAlpha",
    6: "oneMinusSrcColor",
    7: "dstAlpha",
    8: "oneMinusDstAlpha",
    9: "srcAlphaSaturate",
    10: "oneMinusSrcAlpha",
}
COLOR_MASK_BITS = (("r", 8), ("g", 4), ("b", 2), ("a", 1))

# What a pass draws with when it says nothing: Unity's own fixed-function defaults.
STATE_DEFAULTS = {"cull": 2.0, "zWrite": 1.0, "zTest": 4.0, "src": 1.0, "dst": 0.0, "mask": 15.0}

# Disjoint across shader families: _Cutoff is the character and scene shaders,
# _AlphaTest and _DetailAlphaTestValue the effect ones, _AlphaTestThresould [sic] only
# XTransparentBloomModify.
CUTOFFS = ("_AlphaTestThresould", "_AlphaTest", "_DetailAlphaTestValue", "_Cutoff")
CLIP_KEYWORDS = ("_ALPHACLIP", "_ALPHATEST_ON")
DEFAULT_CUTOFF = 0.5

QUEUE_BASES = {
    "Background": 1000,
    "Geometry": 2000,
    "AlphaTest": 2450,
    "Transparent": 3000,
    "Overlay": 4000,
}
DEFAULT_QUEUE = QUEUE_BASES["Geometry"]


@dataclass(frozen=True)
class Render:
    """
    The draw state of the shader's main pass, resolved against the material.

    `cull` is Unity's, relative to the authored winding. The writer turns it around
    on geometry it flipped.
    """

    blend: tuple[str, str] | None
    color_mask: str
    depth_write: bool
    z_test: ZTest
    cull: Cull
    alpha_test: float
    render_order: int

    @property
    def alpha_mode(self) -> str:
        if self.blend is not None:
            return "BLEND"
        return "MASK" if self.alpha_test > 0.0 else "OPAQUE"

    def resolve_emitted_cull(self, winding: Winding) -> Cull:
        return FLIPPED_CULL[self.cull] if winding is Winding.REVERSED else self.cull

    def as_dict(self, winding: Winding) -> RenderRow:
        return {
            "blend": None
            if self.blend is None
            else {"src": self.blend[0], "dst": self.blend[1]},
            "colorMask": self.color_mask,
            "depthWrite": self.depth_write,
            "zTest": self.z_test,
            "alphaTest": self.alpha_test,
            "cull": self.resolve_emitted_cull(winding),
            "reversedWinding": winding is Winding.REVERSED,
            "renderOrder": self.render_order,
        }


def resolve_render(main: "Surface") -> Render:
    """
    The printed pass state is only real where nothing binds it. A bound value prints
    as 0 and the material's property is the truth, which is why the shipped
    Character "says" ZTest Off while testing depth like everything else.
    """

    def read(key: str) -> int:
        bound, literal = main.state.get(key, (None, STATE_DEFAULTS[key]))
        if bound is None:
            return int(literal)
        value = main.floats.get(bound)
        if value is None:
            logger.warning(f"{main.name}: {key} bound to {bound}, which it doesn't have")
            return int(STATE_DEFAULTS[key])
        return int(value)

    source, destination = read("src"), read("dst")
    mask = read("mask")
    alpha_test = 0.0
    if any(keyword in main.keywords for keyword in CLIP_KEYWORDS):
        # The game clips and then blends. The cutoff rides along with the blend, so
        # a blended surface with a non-zero alphaTest is the whole state.
        alpha_test = next(
            (main.floats[name] for name in CUTOFFS if name in main.floats),
            DEFAULT_CUTOFF,
        )
    queue = main.custom_render_queue
    return Render(
        blend=None
        if (source, destination) == (1, 0)
        else (BLEND_FACTORS[source], BLEND_FACTORS[destination]),
        color_mask="".join(name for name, bit in COLOR_MASK_BITS if mask & bit),
        depth_write=read("zWrite") != 0,
        z_test=Z_TESTS[read("zTest")],
        cull=CULL[read("cull")],
        alpha_test=alpha_test,
        render_order=queue if queue >= 0 else _parse_queue(main.tags.get(QUEUE_TAG)),
    )


# 113 of 1135 shaders carry no QUEUE tag, plus the 23 authored-null pointers.
# Every one that does carry it parses.
def _parse_queue(tag: str | None) -> int:
    if not tag:
        return DEFAULT_QUEUE

    name, sign, offset = tag.partition("+")
    if not sign:
        name, sign, offset = tag.partition("-")
    base = QUEUE_BASES.get(name.strip())
    if base is None:
        logger.warning(f"QUEUE {tag!r} names no queue, default order")
        return DEFAULT_QUEUE
    if not sign:
        return base
    try:
        shift = int(offset)
    except ValueError:
        logger.warning(f"QUEUE {tag!r} has a junk offset, ignored")
        return base
    return base + (shift if sign == "+" else -shift)
