import pygltflib as gl

from pgr_assets.models.format import (
    MaterialExtras,
    SurfaceRow,
    TextureBindingRow,
    TextureExtras,
    to_plain,
)
from pgr_assets.models.gltf.buffer import Blob
from pgr_assets.models.material import MaterialSet, Surface, TextureRef
from pgr_assets.models.mesh import Geometry
from pgr_assets.models.render import Winding
from pgr_assets.models.texture import BUMP_SLOT, LINEAR, Texture

WEBP_EXTENSION = "EXT_texture_webp"
WEBP_MIME = "image/webp"
BASE_COLOR_SLOT = "_MainTex"

# No mips are emitted, and asking for a mipmapped filter without mips is undefined
# across viewers.
MIN_FILTER = LINEAR


class Shading:
    """
    The glTF image, sampler, texture and material arrays of one document.
    """

    def __init__(self, blob: Blob, textures: dict[str, Texture]) -> None:
        self.images: list[gl.Image] = []
        self.samplers: list[gl.Sampler] = []
        self.textures: list[gl.Texture] = []
        self.materials: list[gl.Material] = []
        self.texture_of: dict[str, int] = {}
        self._samplers: dict[tuple[int, int, int], int] = {}
        for key, texture in textures.items():
            self.images.append(
                gl.Image(
                    name=texture.name,
                    mimeType=WEBP_MIME,
                    bufferView=blob.add_image(texture.webp),
                )
            )
            self.textures.append(
                gl.Texture(
                    name=texture.name,
                    sampler=self._resolve_sampler(texture),
                    extensions={WEBP_EXTENSION: {"source": len(self.images) - 1}},
                    extras=to_plain(TextureExtras(colorSpace=texture.color_space)),
                )
            )
            self.texture_of[key] = len(self.textures) - 1

    def _resolve_sampler(self, texture: Texture) -> int:
        signature = (texture.wrap_s, texture.wrap_t, texture.mag_filter)
        if signature not in self._samplers:
            self.samplers.append(
                gl.Sampler(
                    wrapS=texture.wrap_s,
                    wrapT=texture.wrap_t,
                    magFilter=texture.mag_filter,
                    minFilter=MIN_FILTER,
                )
            )
            self._samplers[signature] = len(self.samplers) - 1
        return self._samplers[signature]

    def add(self, materials: MaterialSet, geometry: Geometry, winding: Winding) -> int:
        """
        Emit a material and every pass drawn over its geometry, passes first.
        """
        passes = [self.add(p, geometry, winding) for p in materials.passes]
        main = materials.main
        render = materials.render
        textured = bool(geometry.uvs)
        base = self._find_binding(main, BASE_COLOR_SLOT) if textured else None
        normal = self._find_binding(main, BUMP_SLOT) if textured else None
        extras: MaterialExtras = {
            "family": main.family,
            "render": render.as_dict(winding),
            "shader": self._emit_surface(main, geometry),
        }
        if passes:
            extras["passes"] = passes
        material = gl.Material(
            name=main.name,
            pbrMetallicRoughness=gl.PbrMetallicRoughness(
                # Both default to 1.0 in glTF, and a fully metallic surface with no
                # environment renders black.
                metallicFactor=0.0,
                roughnessFactor=1.0,
                baseColorTexture=(
                    None
                    if base is None
                    else gl.TextureInfo(
                        index=self.texture_of[base.key],
                        texCoord=geometry.resolve_tex_coord(base.source_uv),
                    )
                ),
            ),
            normalTexture=(
                None
                if normal is None
                else gl.NormalMaterialTexture(
                    index=self.texture_of[normal.key],
                    texCoord=geometry.resolve_tex_coord(normal.source_uv),
                )
            ),
            alphaMode=render.alpha_mode,
            doubleSided=render.resolve_emitted_cull(winding) == "none",
            extras=to_plain(extras),
        )
        if render.alpha_mode == "MASK":
            material.alphaCutoff = render.alpha_test
        self.materials.append(material)
        return len(self.materials) - 1

    def _find_binding(self, surface: Surface, slot: str) -> TextureRef | None:
        """
        The slot's binding, when its texture made it into the document.
        """
        return next(
            (r for r in surface.textures if r.slot == slot and r.key in self.texture_of),
            None,
        )

    def _emit_surface(self, surface: Surface, geometry: Geometry) -> SurfaceRow:
        emitted: SurfaceRow = {
            "base": surface.base_shader,
            "keywords": surface.keywords,
            "textures": self._emit_bindings(surface, geometry),
            "floats": surface.floats,
            "colors": surface.colors,
            "vectors": surface.vectors,
        }
        if surface.cubemap is not None:
            emitted["cubemap"] = surface.cubemap
        if surface.emission_flow is not None:
            emitted["emissionFlow"] = surface.emission_flow.as_dict()
        return emitted

    def _emit_bindings(
        self, surface: Surface, geometry: Geometry
    ) -> dict[str, TextureBindingRow]:
        # Unity's own ST, in Unity UV space. The mesh TEXCOORDs are V flipped,
        # the bindings aren't, a reader converts once.
        return {
            ref.slot: {
                "index": self.texture_of[ref.key],
                "texCoord": geometry.resolve_tex_coord(ref.source_uv),
                "scale": list(ref.scale),
                "offset": list(ref.offset),
            }
            for ref in surface.textures
            if ref.key in self.texture_of
        }
