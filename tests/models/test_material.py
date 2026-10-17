import itertools
import unittest
from types import SimpleNamespace

from pgr_assets.models.library import CubemapLibrary
from pgr_assets.models.material import (
    MaterialSet,
    Surface,
    read_materials,
    resolve_uv3_layout,
)
from pgr_assets.models.mesh import Uv3Layout
from pgr_assets.models.render import Winding, resolve_render
from pgr_assets.models.shader import parse_shader_name
from pgr_assets.models.texture import TextureSet

CHARACTER = "Variant/XCharacter/Character"
OUTLINE = "XCharacter/Outline"
SPARKLE = "XCharacter/CharacterSparkle"
EFFECT = "XEffect/Effect"
STENCIL = "XShadowVolume/StencilVolumeFrontBack"
PBR = "Variant/XScene/XScenePBR"
FUR = "XFur"


class NoTextures(TextureSet):
    def add(self, pointer, slot, where):
        return None


SHADER_IDS = itertools.count()

# Pass 0 the way Character prints it: every state value bound to a property.
BOUND = {
    "culling": "_Cull",
    "zWrite": "_ZWrite",
    "zTest": "_ZTest",
    "srcBlend": "_SrcBlend",
    "destBlend": "_DstBlend",
    "colMask": "_ColorMask",
}
DECLARED = {
    "_Cull": 2.0,
    "_ZWrite": 1.0,
    "_ZTest": 4.0,
    "_SrcBlend": 1.0,
    "_DstBlend": 0.0,
    "_ColorMask": 15.0,
}


def reader() -> SimpleNamespace:
    return SimpleNamespace(
        assets_file=SimpleNamespace(name="shader.ab"), path_id=next(SHADER_IDS)
    )


def shader(
    variant: str,
    tags: dict | None = None,
    literals: dict | None = None,
    declared: dict | None = None,
):
    def value(key: str):
        if key in (literals or {}):
            return SimpleNamespace(name="<noninit>", val=literals[key])
        return SimpleNamespace(name=BOUND[key], val=0.0)

    state = SimpleNamespace(
        culling=value("culling"),
        zWrite=value("zWrite"),
        zTest=value("zTest"),
        rtBlend0=SimpleNamespace(
            srcBlend=value("srcBlend"),
            destBlend=value("destBlend"),
            colMask=value("colMask"),
        ),
    )
    props = [
        SimpleNamespace(
            m_Name=name,
            m_Type=2,
            m_DefValue_0_=default,
            m_DefValue_1_=0.0,
            m_DefValue_2_=0.0,
            m_DefValue_3_=0.0,
        )
        for name, default in (DECLARED | (declared or {})).items()
    ]
    # Two subshaders, the untagged-for-QUEUE one first, so a lookup that takes
    # the first tagged subshader loses the queue.
    passes = [SimpleNamespace(m_State=state)]
    decoy = SimpleNamespace(
        m_Tags=SimpleNamespace(tags=[("RenderType", "Opaque")]), m_Passes=passes
    )
    real = SimpleNamespace(
        m_Tags=SimpleNamespace(tags=list((tags or {}).items())), m_Passes=passes
    )
    return SimpleNamespace(
        object_reader=reader(),
        m_ParsedForm=SimpleNamespace(
            m_Name=variant,
            m_SubShaders=[decoy, real],
            m_PropInfo=SimpleNamespace(m_Props=props),
        ),
    )


def material(
    name: str,
    variant: str,
    floats=None,
    tags=None,
    queue: int = -1,
    valid=None,
    literals=None,
    declared=None,
):
    parsed = shader(variant, tags, literals, declared)
    asset = SimpleNamespace(
        object_reader=reader(),
        m_Name=name,
        m_Shader=SimpleNamespace(
            deref=lambda: parsed.object_reader, read=lambda: parsed
        ),
        m_CustomRenderQueue=queue,
        m_ValidKeywords=valid,
        m_SavedProperties=SimpleNamespace(
            m_Floats=list((floats or {}).items()), m_Colors=[], m_TexEnvs=[]
        ),
    )
    return SimpleNamespace(m_PathID=1, read=lambda: asset)


def renderer(*materials):
    return SimpleNamespace(m_Materials=list(materials))


def read(*materials):
    return read_materials(renderer(*materials), NoTextures(), CubemapLibrary(), "part")


class ShaderNameTest(unittest.TestCase):
    def test_keywords_come_off_the_variant_tail(self):
        base, _, keywords = parse_shader_name(
            shader(f"{CHARACTER}-Variant-_CHAR_SHADOWMAP-_XBUMP")
        )
        self.assertEqual(CHARACTER, base)
        self.assertEqual(["_CHAR_SHADOWMAP", "_XBUMP"], keywords)


class PassKeywordTest(unittest.TestCase):
    def test_an_outline_pass_takes_its_keywords_off_the_material(self):
        result = read(
            material("Body", f"{CHARACTER}-Variant-_XBUMP", valid=["_XDITHER"]),
            material("BodyOL", OUTLINE, valid=["_OUTLINE_VERTEX_COLOR"]),
        )
        assert isinstance(result, MaterialSet)
        self.assertEqual(["_XBUMP"], result.main.keywords)
        self.assertEqual(["_OUTLINE_VERTEX_COLOR"], result.passes[0].main.keywords)


class SelectionTest(unittest.TestCase):
    def test_an_auxiliary_material_at_index_zero_does_not_win(self):
        result = read(
            material("BodyOL", OUTLINE), material("Body", f"{CHARACTER}-Variant")
        )
        assert isinstance(result, MaterialSet)
        self.assertEqual("Body", result.main.name)
        self.assertEqual(["outline"], [p.main.family for p in result.passes])

    def test_a_character_surface_beats_an_earlier_non_auxiliary_one(self):
        result = read(material("Fx", EFFECT), material("Body", CHARACTER))
        assert isinstance(result, MaterialSet)
        self.assertEqual("Body", result.main.name)
        self.assertEqual(["effect"], [p.main.family for p in result.passes])

    def test_the_first_non_auxiliary_wins_when_no_character_surface_is_present(self):
        result = read(material("Fx", EFFECT), material("Fur", "XFur"))
        assert isinstance(result, MaterialSet)
        self.assertEqual("Fx", result.main.name)

    def test_an_all_auxiliary_renderer_draws_nothing(self):
        self.assertIsNone(
            read(material("BodyOL", OUTLINE), material("BodySK", SPARKLE))
        )

    def test_a_stencil_volume_takes_the_whole_renderer_with_it(self):
        self.assertIsNone(read(material("Vol", STENCIL), material("Body", CHARACTER)))


class RenderStateTest(unittest.TestCase):
    def render(self, floats, tags=None, queue=-1, variant=CHARACTER, **shader_args):
        result = read(material("Body", variant, floats, tags, queue, **shader_args))
        assert isinstance(result, MaterialSet)
        return result

    def test_cull_off_is_none(self):
        self.assertEqual("none", self.render({"_Cull": 0.0}).render.cull)

    def test_an_unsaved_cull_takes_the_declared_default(self):
        self.assertEqual("back", self.render({}).render.cull)

    def test_cull_front_is_turned_around_on_flipped_geometry(self):
        render = self.render({"_Cull": 1.0}).render
        self.assertEqual("front", render.cull)
        emitted = render.as_dict(Winding.REVERSED)
        self.assertEqual("back", emitted["cull"])
        self.assertTrue(emitted["reversedWinding"])

    def test_a_literal_ignores_a_saved_property(self):
        # XFur prints Cull Off with no property behind it.
        render = self.render({"_Cull": 2.0}, variant=FUR, literals={"culling": 0.0})
        self.assertEqual("none", render.render.cull)

    def test_over_is_its_factor_pair(self):
        render = self.render({"_SrcBlend": 5.0, "_DstBlend": 10.0}).render
        self.assertEqual("BLEND", render.alpha_mode)
        self.assertEqual(("srcAlpha", "oneMinusSrcAlpha"), render.blend)

    def test_one_zero_is_opaque(self):
        self.assertIsNone(self.render({}).render.blend)

    def test_blending_beats_clipping(self):
        result = self.render(
            {"_SrcBlend": 5.0, "_DstBlend": 10.0, "_AlphaTestThresould": 0.05},
            variant=f"{CHARACTER}-Variant-_ALPHACLIP",
        )
        self.assertEqual("BLEND", result.render.alpha_mode)
        self.assertAlmostEqual(0.05, result.render.alpha_test)

    def test_clipping_without_blending_is_a_mask(self):
        render = self.render(
            {"_AlphaTest": 0.157}, variant=f"{CHARACTER}-Variant-_ALPHATEST_ON"
        ).render
        self.assertEqual("MASK", render.alpha_mode)
        self.assertAlmostEqual(0.157, render.alpha_test)

    def test_a_clip_with_no_authored_cutoff_falls_back(self):
        render = self.render({}, variant=f"{CHARACTER}-Variant-_ALPHACLIP").render
        self.assertAlmostEqual(0.5, render.alpha_test)

    def test_a_declared_zwrite_off_holds_when_nothing_is_saved(self):
        # XEffect/Effect declares _ZWrite 0. A material that never touched it draws
        # without depth writes, whatever a reader's fallback would have assumed.
        render = self.render({}, variant=EFFECT, declared={"_ZWrite": 0.0}).render
        self.assertFalse(render.depth_write)

    def test_color_mask_bits_spell_the_channels(self):
        self.assertEqual("rgb", self.render({"_ColorMask": 14.0}).render.color_mask)
        bloom = self.render({}, literals={"colMask": 1.0}).render
        self.assertEqual("a", bloom.color_mask)

    def test_the_queue_tag_resolves_the_minus_one_sentinel(self):
        render = self.render({}, tags={"QUEUE": "Transparent+15"}, queue=-1).render
        self.assertEqual(3015, render.render_order)

    def test_a_custom_queue_beats_the_tag(self):
        render = self.render({}, tags={"QUEUE": "Geometry"}, queue=3000).render
        self.assertEqual(3000, render.render_order)

    def test_an_unusable_queue_tag_falls_back_to_geometry(self):
        render = self.render({}, tags={"QUEUE": "Nonsense"}).render
        self.assertEqual(2000, render.render_order)


def material_set(main: str, *passes: str) -> MaterialSet:
    def single(name: str, base: str) -> MaterialSet:
        surface = Surface(name, base)
        return MaterialSet(surface, resolve_render(surface))

    return MaterialSet(
        Surface("main", main),
        resolve_render(Surface("main", main)),
        [single(f"pass{index}", base) for index, base in enumerate(passes)],
    )


class WantsSmoothNormalTest(unittest.TestCase):
    def test_a_character_main_or_an_outline_converts_unless_the_main_is_scene(self):
        cases = [
            ((CHARACTER,), True),
            ((CHARACTER, OUTLINE), True),
            ((FUR, OUTLINE), True),
            ((FUR,), False),
            ((PBR,), False),
            ((PBR, OUTLINE), False),
            ((EFFECT,), False),
            (("",), False),
        ]
        for shaders, expected in cases:
            with self.subTest(shaders=shaders):
                self.assertIs(
                    expected,
                    resolve_uv3_layout(material_set(*shaders))
                    is Uv3Layout.SMOOTH_NORMAL,
                )


if __name__ == "__main__":
    unittest.main()
