from dataclasses import dataclass

from pgr_assets.models.material import MaterialSet
from pgr_assets.models.mesh import Geometry
from pgr_assets.models.render import Winding
from pgr_assets.models.rig import Skin


@dataclass(frozen=True)
class Part:
    node: int
    geometry: Geometry
    materials: MaterialSet
    skin: Skin | None = None

    @property
    def winding(self) -> Winding:
        """
        Cull front is cull back on reversed triangles, which plain glTF can draw, so
        the build reverses those.
        """
        return Winding.REVERSED if self.materials.render.cull == "front" else Winding.AUTHORED
