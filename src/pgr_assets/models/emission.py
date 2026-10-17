import logging
from dataclasses import dataclass
from itertools import pairwise

from pgr_assets.models.format import Curve, EmissionFlowRow, round5
from pgr_assets.models.prefab import Prefab
from pgr_assets.models.unity import read_curve, read_tree

logger = logging.getLogger("pgr-assets")

FLOW_SCRIPT = "XEmissionFlowController"
FLOW_SLOT = "_EmissionFlowMap"

DEFAULT_CURVE: Curve = [[0.0, 0.0, 1.0, 1.0], [1.0, 1.0, 1.0, 1.0]]

def evaluate_curve(curve: Curve, time: float) -> float:
    """
    Unity's AnimationCurve.Evaluate: cubic Hermite per segment, clamped at the ends.
    """
    if not curve:
        return 0.0
    if time <= curve[0][0]:
        return curve[0][1]
    if time >= curve[-1][0]:
        return curve[-1][1]

    for left, right in pairwise(curve):
        if time <= right[0]:
            return _interpolate_hermite(left, right, time)
    # NaN key times fail every comparison above
    return curve[-1][1]


def _interpolate_hermite(left: list[float], right: list[float], time: float) -> float:
    span = right[0] - left[0]
    if span <= 0.0:
        return right[1]
    u = (time - left[0]) / span
    u2 = u * u
    u3 = u2 * u
    return (
        (2.0 * u3 - 3.0 * u2 + 1.0) * left[1]
        + (u3 - 2.0 * u2 + u) * span * left[3]
        + (-2.0 * u3 + 3.0 * u2) * right[1]
        + (u3 - u2) * span * right[2]
    )


@dataclass
class EmissionFlow:
    speed: float
    start_flow: float
    extended_range: int
    use_animation: bool
    curve: Curve

    @property
    def resting_st(self) -> tuple[tuple[float, float], tuple[float, float]]:
        scale = (1.0, 1.0 / self.extended_range)
        return scale, (0.0, round5(evaluate_curve(self.curve, self.start_flow % 1.0)))

    def as_dict(self) -> EmissionFlowRow:
        return {
            "speed": round5(self.speed),
            "startFlow": round5(self.start_flow),
            "extendedRange": self.extended_range,
            "useAnimation": self.use_animation,
            "curve": [[round5(v) for v in key] for key in self.curve],
        }


def read_flow(tree: dict) -> EmissionFlow:
    return EmissionFlow(
        speed=float(tree["Speed"]),
        start_flow=float(tree["StartFlow"]),
        # ExtendedRange divides, and the inspector clamps it at 1 rather than 0.
        extended_range=max(int(tree["ExtendedRange"]), 1),
        use_animation=bool(tree["UseAnimation"]),
        curve=read_curve(tree["Curve"]) or DEFAULT_CURVE,
    )


def read_emission_flow(prefab: Prefab) -> dict[int, EmissionFlow]:
    skinned = {r.node for r in prefab.renderers if r.skinned} | prefab.hidden_skinned

    flows: dict[int, EmissionFlow] = {}
    for node, _, component in prefab.find_components(FLOW_SCRIPT):
        name = prefab.nodes[node].name
        if node not in skinned:
            logger.warning(f"{name}: {FLOW_SCRIPT} on no skinned renderer, ignored")
            continue
        flow = read_tree(component, name, "emission flow", read_flow)
        if flow is not None:
            flows[node] = flow
    return flows
