import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Protocol, cast

from PIL import Image
from UnityPy import classes

from pgr_assets.converters.unity_to_json import jsonify

from .models import BoneFollower, Spine, SpineInfo
from .quirks import apply_quirk

logger = logging.getLogger("spine-extractor")


# PGR-specific MonoBehaviour scripts. UnityPy resolves these fields from the
# Unity type tree at runtime, so they aren't on its typed classes. These
# Protocols describe the shapes; `_script` reinterprets an object as one once
# its script class has been confirmed at runtime.
class _AtlasAsset(Protocol):
    atlasFile: classes.PPtr[classes.TextAsset]
    materials: list[classes.PPtr[classes.Material]]


class _SkeletonDataAsset(Protocol):
    scale: float
    skeletonJSON: classes.PPtr[classes.TextAsset]
    atlasAssets: list[classes.PPtr[_AtlasAsset]]


class _SkeletonGraphic(Protocol):
    m_Material: classes.PPtr[classes.Material]
    skeletonDataAsset: classes.PPtr[_SkeletonDataAsset]


class _BoneFollowerGraphic(Protocol):
    boneName: str
    skeletonGraphic: classes.PPtr[_SkeletonGraphic]


class _UiObject(Protocol):
    ObjList: list[Any]


class _XEffectScaler(Protocol):
    DesignWidth: float
    DesignHeight: float


def _script[T](obj: object, _proto: type[T]) -> T:
    """
    Reinterpret a UnityPy object as the given MonoBehaviour Protocol.

    This is an *unchecked* cast and performs no runtime or static validation:
    the Protocols only document the expected field shapes. The caller is
    responsible for having confirmed ``m_Script.read().m_ClassName`` matches
    before calling, otherwise attribute access will fail at runtime.
    """
    return cast(Any, obj)


def _path_id(obj: classes.Object) -> int:
    assert obj.object_reader is not None
    return obj.object_reader.path_id


def _component_ptr(
    entry: classes.ComponentPair | tuple[int, classes.PPtr[classes.Component]],
) -> classes.PPtr[classes.Component]:
    return entry.component if isinstance(entry, classes.ComponentPair) else entry[1]


# SkeletonGraphic draws in canvas pixels, 100 per unit
GRAPHIC_PIXELS_PER_UNIT = 100

SKELETON_CLASSES = frozenset({"SkeletonGraphic", "SkeletonRenderer"})


@dataclass(frozen=True)
class Placement:
    """
    Where a GameObject sits in prefab root space, and whether it draws at all.
    """

    active: bool = True
    position: tuple[float, float] = (0.0, 0.0)
    scale: float = 1.0

    # x scale stands in for both axes and rotation is ignored, no 4.7.0 rig needs either
    def child(self, transform: classes.Transform, active: bool) -> "Placement":
        pos = transform.m_LocalPosition
        scale = transform.m_LocalScale
        assert pos is not None and scale is not None
        return Placement(
            self.active and active,
            (
                self.position[0] + pos.x * self.scale,
                self.position[1] + pos.y * self.scale,
            ),
            self.scale * scale.x,
        )


def texture_from_material(mat: classes.Material) -> tuple[str, Image.Image] | None:
    for name, tex_env in mat.m_SavedProperties.m_TexEnvs:
        if name == "_MainTex":
            if tex_env.m_Texture.path_id == 0:
                return None
            t = cast(classes.Texture2D, tex_env.m_Texture.read())
            return t.m_Name, t.image
    return None


def crawl(
    go: classes.GameObject,
    spine: Spine,
    parent: Placement,
    followers: tuple[BoneFollower, ...] = (),
) -> None:
    """
    Walk the prefab hierarchy depth first, parents before children, which is
    also the order uGUI draws in. Every skeleton below a BoneFollowerGraphic
    rides its bone
    """
    components = [_component_ptr(x).read() for x in go.m_Component]
    transform = next(
        c
        for c in components
        if isinstance(c, (classes.RectTransform, classes.Transform))
    )
    here = parent.child(transform, bool(go.m_IsActive))
    scripts = [
        (c, c.m_Script.read().m_ClassName)
        for c in components
        if isinstance(c, classes.MonoBehaviour)
    ]

    # A follower also carries a skeleton on its own GameObject
    for obj, class_name in scripts:
        if class_name == "BoneFollowerGraphic":
            follower = handle_bone_follower(obj)
            spine.bone_followers.append(follower)
            followers = (*followers, follower)

    for obj, class_name in scripts:
        if class_name in SKELETON_CLASSES:
            if not here.active:
                continue
            skeleton = handle_skeleton(go, components, here)
            if skeleton is not None:
                spine.spines.append(skeleton)
                for follower in followers:
                    follower.spines.add(skeleton.name)
        elif class_name == "UiObject":
            logger.debug("Got UiObject -> likely Movie Spine")
            ui = _script(obj, _UiObject)
            spine.spine_order_list = [x.path_id for x in ui.ObjList]
            spine.found_size = (1000, 1080)
        elif class_name == "XEffectScaler":
            scaler = _script(obj, _XEffectScaler)
            spine.found_size = (round(scaler.DesignWidth), round(scaler.DesignHeight))

    for child in transform.m_Children or []:
        crawl(
            cast(classes.GameObject, child.read().m_GameObject.read()),
            spine,
            here,
            followers,
        )


def handle_skeleton(
    skeleton_object: classes.GameObject,
    components: list[Any],
    here: Placement,
) -> SpineInfo | None:
    spine = SpineInfo("<unknown>", skeleton_object.m_Name)
    spine.ids.add(_path_id(skeleton_object))
    # float32 soup, 0.01 * 100 lands on 0.99999998 otherwise
    spine.position = (round(here.position[0], 4), round(here.position[1], 4))

    for obj in components:
        spine.ids.add(_path_id(obj))

        if isinstance(obj, classes.RectTransform):
            pivot = obj.m_Pivot
            assert pivot is not None
            spine.pivot = (pivot.x, pivot.y)
        elif not isinstance(obj, classes.Transform):
            sort_order: int | None = getattr(obj, "m_SortingOrder", None)
            if sort_order is not None:
                spine.order = sort_order

        if not isinstance(obj, classes.MonoBehaviour):
            continue

        script_type = obj.m_Script.read().m_ClassName
        anim = getattr(obj, "_animationName", None) or getattr(
            obj, "animationName", None
        )
        if anim:
            spine.default_animation = anim

        if script_type in SKELETON_CLASSES:
            sk = _script(obj, _SkeletonGraphic)
            # Try get the texture from the material, this is one route, the other is through the atlas assets
            if script_type == "SkeletonGraphic" and sk.m_Material.path_id != 0:
                tex = texture_from_material(sk.m_Material.read())
                if tex is not None:
                    spine.textures.append(tex)

            skeleton_data_asset = sk.skeletonDataAsset.read()
            scale = here.scale * skeleton_data_asset.scale
            if script_type == "SkeletonGraphic":
                scale *= GRAPHIC_PIXELS_PER_UNIT
            spine.scale = round(scale, 4)

            skeleton_json = skeleton_data_asset.skeletonJSON.read()
            spine.name = skeleton_json.m_Name
            spine.json = skeleton_json.m_Script

            atlas_asset = skeleton_data_asset.atlasAssets[0].read()
            spine.atlas = atlas_asset.atlasFile.read().m_Script
            for mat in atlas_asset.materials:
                tex = texture_from_material(mat.read())
                if tex is not None:
                    spine.textures.append(tex)
        elif script_type == "XEffectScaler":
            scaler = _script(obj, _XEffectScaler)
            spine.size = (round(scaler.DesignWidth), round(scaler.DesignHeight))

    if spine.valid():
        logger.debug(f"Found spine: {spine}")
        return spine
    else:
        logger.warning(f"Invalid spine: {spine}")
        return None


def handle_bone_follower(obj: classes.MonoBehaviour) -> BoneFollower:
    follower_script = _script(obj, _BoneFollowerGraphic)
    return BoneFollower(
        follower_script.boneName,
        follower_script.skeletonGraphic.read()
        .skeletonDataAsset.read()
        .skeletonJSON.read()
        .m_Name,
    )


def extract_spine(
    name: str,
    obj: list[classes.GameObject],
    output_dir: str,
    write_json: bool = False,
) -> None:
    spine = Spine(name)

    for o in obj:
        crawl(o, spine, Placement())

    spine.finalize()
    apply_quirk(spine)

    if len(spine.spines) > 0:
        spine.write(output_dir)
    else:
        logger.debug(f"Processed {name} but no spines found")

    # jsonify follows every PPtr and faults in whatever the prefab reaches,
    # fine for an opt-in debugging dump
    if write_json and obj:
        json_dir = os.path.join(output_dir, name)
        os.makedirs(json_dir, exist_ok=True)
        with open(os.path.join(json_dir, "jsonified.json"), "w") as f:
            json.dump(
                jsonify(obj[-1]),
                f,
                indent=4,
                default=lambda x: f"<unserializable {type(x).__name__}>",
            )
