import logging
from dataclasses import dataclass, field
from functools import partial
from typing import Any, cast

import numpy as np

from pgr_assets.models import coords
from pgr_assets.models.format import (
    ColliderBound,
    ColliderKind,
    Curve,
    SpringChainRow,
    SpringColliderRow,
    SpringPresetRow,
    SpringsRow,
    round5,
)
from pgr_assets.models.prefab import Prefab
from pgr_assets.models.unity import (
    read_curve,
    read_pointer,
    read_tree,
    resolve_asset_key,
)

logger = logging.getLogger("pgr-assets")

CHAIN_SCRIPT = "XDynamicBone"
COLLIDER_KINDS: dict[str, ColliderKind] = {
    "XDynamicBoneCollider": "capsule",
    "XDynamicBonePlaneCollider": "plane",
}
SPRING_SCRIPTS = (CHAIN_SCRIPT, *COLLIDER_KINDS)

def read_curve_keys(raw: Any) -> Curve | None:
    """
    Zero keys and flat 1.0 both mean no falloff, so both reduce to None. The engine
    skips a zero-key curve and a flat one multiplies by one. A value of 1.0 at every
    key is not enough, since a slope still bends the segment between two of them.
    """
    keys = read_curve(raw)
    if not keys:
        return None
    if all(k[1] == 1.0 and k[2] == 0.0 and k[3] == 0.0 for k in keys):
        return None
    return keys


def _read_vec(raw: Any) -> list[float]:
    return coords.flip_z(np.array([raw["x"], raw["y"], raw["z"]])).tolist()


def _round_deep(value: Any) -> Any:
    if isinstance(value, float):
        return round5(value)
    if isinstance(value, list):
        return [_round_deep(v) for v in value]
    if isinstance(value, dict):
        return {k: _round_deep(v) for k, v in value.items()}
    return value


@dataclass
class SpringPreset:
    name: str
    damping: float
    elasticity: float
    stiffness: float
    inert: float
    weight: float
    gravity: list[float]
    force: list[float]
    freeze_axis: int
    damping_curve: Curve | None = None
    elasticity_curve: Curve | None = None
    stiffness_curve: Curve | None = None
    inert_curve: Curve | None = None

    def as_dict(self) -> SpringPresetRow:
        row: SpringPresetRow = {
            "name": self.name,
            "damping": self.damping,
            "elasticity": self.elasticity,
            "stiffness": self.stiffness,
            "inert": self.inert,
            "weight": self.weight,
            "gravity": self.gravity,
            "force": self.force,
            "freezeAxis": self.freeze_axis,
        }
        if self.damping_curve is not None:
            row["dampingCurve"] = self.damping_curve
        if self.elasticity_curve is not None:
            row["elasticityCurve"] = self.elasticity_curve
        if self.stiffness_curve is not None:
            row["stiffnessCurve"] = self.stiffness_curve
        if self.inert_curve is not None:
            row["inertCurve"] = self.inert_curve
        return row


@dataclass
class SpringCollider:
    node: int
    kind: ColliderKind
    center: list[float]
    axis: int
    bound: ColliderBound
    radius: float | None = None
    height: float | None = None

    def as_dict(self) -> SpringColliderRow:
        """
        DynamicBone's own reading: a capsule no longer than it is wide is a sphere,
        and a plane's normal is its direction axis. `center` is already mirrored,
        so the axis gets the same Z flip.
        """
        axis = coords.flip_z(np.eye(3)[self.axis])
        center = np.array(self.center)
        if self.kind == "plane":
            row: SpringColliderRow = {
                "node": self.node,
                "kind": "plane",
                "bound": self.bound,
                "center": self.center,
                "normal": axis.tolist(),
            }
            return row

        radius = self.radius or 0.0
        half = (self.height or 0.0) * 0.5 - radius
        row = {"node": self.node, "kind": "sphere", "bound": self.bound}
        if half > 0:
            row["kind"] = "capsule"
            row["ends"] = [(center - axis * half).tolist(), (center + axis * half).tolist()]
        else:
            row["center"] = self.center
        row["radius"] = radius
        return row


@dataclass
class SpringChain:
    node: int
    root: int
    preset: int
    radius: float
    colliders: list[int] = field(default_factory=list)
    exclusions: list[int] = field(default_factory=list)
    end_length: float = 0.0
    end_offset: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    radius_curve: Curve | None = None
    max_wind_force: float = 1.0
    wind_curve: Curve | None = None
    max_wind_curve: Curve | None = None

    def as_dict(self) -> SpringChainRow:
        row: SpringChainRow = {
            "node": self.node,
            "root": self.root,
            "preset": self.preset,
            "radius": self.radius,
        }
        if self.colliders:
            row["colliders"] = self.colliders
        if self.exclusions:
            row["exclusions"] = self.exclusions
        if self.end_length:
            row["endLength"] = self.end_length
        if any(self.end_offset):
            row["endOffset"] = self.end_offset
        if self.radius_curve is not None:
            row["radiusCurve"] = self.radius_curve
        if self.max_wind_force != 1.0:
            row["maxWindForce"] = self.max_wind_force
        if self.wind_curve is not None:
            row["windCurve"] = self.wind_curve
        if self.max_wind_curve is not None:
            row["maxWindCurve"] = self.max_wind_curve
        return row


@dataclass
class Springs:
    presets: list[SpringPreset] = field(default_factory=list)
    colliders: list[SpringCollider] = field(default_factory=list)
    chains: list[SpringChain] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.chains)

    def as_dict(self) -> SpringsRow:
        row: SpringsRow = {
            "presets": [preset.as_dict() for preset in self.presets],
            "chains": [chain.as_dict() for chain in self.chains],
        }
        if self.colliders:
            row["colliders"] = [collider.as_dict() for collider in self.colliders]
        return cast(SpringsRow, _round_deep(row))


def read_preset(name: str, tree: dict) -> SpringPreset:
    return SpringPreset(
        name=name,
        damping=float(tree["Damping"]),
        # [sic], the game's spelling
        elasticity=float(tree["Elasticty"]),
        stiffness=float(tree["Stiffness"]),
        inert=float(tree["Inert"]),
        weight=float(tree["ConfigWeight"]),
        gravity=_read_vec(tree["Gravity"]),
        force=_read_vec(tree["Force"]),
        freeze_axis=int(tree["FreezeAxis"]),
        damping_curve=read_curve_keys(tree["DampingDistribute"]),
        elasticity_curve=read_curve_keys(tree["ElasticityDistribute"]),
        stiffness_curve=read_curve_keys(tree["StiffnessDistribute"]),
        inert_curve=read_curve_keys(tree["InertDistribute"]),
    )


def read_collider(node: int, kind: ColliderKind, tree: dict) -> SpringCollider:
    # A plane collider has neither.
    radius = tree.get("Radius")
    height = tree.get("Height")
    return SpringCollider(
        node=node,
        kind=kind,
        center=_read_vec(tree["Center"]),
        axis=int(tree["XDirection"]),
        bound="inside" if tree["XBound"] else "outside",
        radius=None if radius is None else float(radius),
        height=None if height is None else float(height),
    )


def read_springs(prefab: Prefab) -> Springs:
    springs = Springs()
    collider_of_key: dict[str, int] = {}
    for node, script, component in prefab.find_components(*COLLIDER_KINDS):
        kind = COLLIDER_KINDS[script]
        name = prefab.nodes[node].name
        collider = read_tree(component, name, script, partial(read_collider, node, kind))
        if collider is None:
            continue
        collider_of_key[resolve_asset_key(component)] = len(springs.colliders)
        springs.colliders.append(collider)

    presets: dict[str, SpringPreset] = {}
    for node, script, component in prefab.find_components(CHAIN_SCRIPT):
        name = prefab.nodes[node].name
        tree = read_tree(component, name, script, lambda tree: tree)
        if tree is None:
            continue

        root = prefab.resolve_node(component, tree["Root"])
        if root is None:
            logger.warning(f"{prefab.name}: spring chain on {name} has no usable root")
            continue

        preset = _read_preset(prefab, component, tree["BoneDataSO"], name, presets)
        if preset is None:
            logger.warning(f"{prefab.name}: spring chain on {name} has no usable preset")
            continue

        try:
            chain = read_chain(
                node,
                root,
                preset,
                _resolve_references(prefab, component, tree["Colliders"], collider_of_key, name),
                _resolve_references(prefab, component, tree["Exclusions"], prefab.node_of, name),
                tree,
            )
        except (KeyError, TypeError, ValueError) as error:
            logger.warning(f"{name}: {script} malformed, {type(error).__name__}: {error}")
            continue
        springs.chains.append(chain)

    springs.presets = list(presets.values())
    return springs


def _resolve_references(
    prefab: Prefab, component: Any, raws: Any, table: dict[str, int], name: str
) -> list[int]:
    resolved: list[int] = []
    for raw in raws:
        if prefab.resolve_pointer(component, raw) is None:
            # Empty slots are authored all over, a warning each is noise.
            logger.debug(f"{name}: empty spring reference slot")
            continue
        key = prefab.resolve_key(component, raw)
        index = None if key is None else table.get(key)
        if index is None:
            logger.warning(f"{name}: spring reference does not resolve, dropped")
            continue
        resolved.append(index)
    return resolved


def _read_preset(
    prefab: Prefab,
    component: Any,
    raw: Any,
    name: str,
    presets: dict[str, SpringPreset],
) -> int | None:
    """
    The chain's preset as an index into `presets`, interning it on first sight.
    """
    pointer = prefab.resolve_pointer(component, raw)
    asset = read_pointer(pointer, name, "spring preset")
    if asset is None:
        return None
    key = resolve_asset_key(asset)
    if key not in presets:
        preset = read_tree(
            asset, name, "spring preset", lambda tree: read_preset(str(tree["m_Name"]), tree)
        )
        if preset is None:
            return None
        presets[key] = preset
    return list(presets).index(key)


def read_chain(
    node: int,
    root: int,
    preset: int,
    colliders: list[int],
    exclusions: list[int],
    tree: dict,
) -> SpringChain:
    return SpringChain(
        node=node,
        root=root,
        preset=preset,
        radius=float(tree["Radius"]),
        colliders=colliders,
        exclusions=exclusions,
        end_length=float(tree["EndLength"]),
        end_offset=_read_vec(tree["EndOffset"]),
        radius_curve=read_curve_keys(tree["RadiusDistribute"]),
        max_wind_force=float(tree["MaxWindForce"]),
        wind_curve=read_curve_keys(tree["WindDynamicCurve"]),
        max_wind_curve=read_curve_keys(tree["MaxWindForceCurve"]),
    )
