import json
import logging
import os
from typing import Any, Optional, Protocol, TypeVar, cast

from UnityPy import classes
from UnityPy.enums import ClassIDType

from pgr_assets.converters.unity_to_json import jsonify

from .models import BoneFollower, Spine, SpineInfo
from .quirks import apply_quirk

logger = logging.getLogger("spine-extractor")

_T = TypeVar("_T")


# PGR-specific MonoBehaviour scripts. UnityPy resolves these fields from the
# Unity type tree at runtime, so they aren't on its typed classes. These
# Protocols describe the shapes; `_script` reinterprets an object as one once
# its script class has been confirmed at runtime.
class _AtlasAsset(Protocol):
    atlasFile: classes.PPtr[classes.TextAsset]
    materials: list[classes.PPtr[classes.Material]]


class _SkeletonDataAsset(Protocol):
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


def _script(obj: object, _proto: type[_T]) -> _T:
    """Reinterpret a UnityPy object as the given MonoBehaviour Protocol.

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


def texture_from_material(mat: classes.Material):
    for name, tex_env in mat.m_SavedProperties.m_TexEnvs:
        if name == "_MainTex":
            if tex_env.m_Texture.path_id == 0:
                return None
            t = cast(classes.Texture2D, tex_env.m_Texture.read())
            return t.m_Name, t.image
    return None


def _record_spine_component(obj: classes.MonoBehaviour, spine: Spine) -> None:
    class_name = obj.m_Script.read().m_ClassName

    if class_name in ("SkeletonGraphic", "SkeletonAnimation"):
        go = obj.m_GameObject.read()
        if go.m_IsActive:
            skeleton = handle_skeleton(_script(go, classes.GameObject))
            if skeleton is not None:
                spine.spines.append(skeleton)
    elif class_name == "BoneFollowerGraphic":
        spine.bone_followers.append(handle_bone_follower(obj))
    elif class_name == "UiObject":
        logger.debug("Got UiObject -> likely Movie Spine")
        ui = _script(obj, _UiObject)
        spine.spine_order_list = [x.path_id for x in ui.ObjList]
        spine.found_size = (1000, 1080)
    elif class_name == "XEffectScaler":
        scaler = _script(obj, _XEffectScaler)
        spine.found_size = (round(scaler.DesignWidth), round(scaler.DesignHeight))


def crawl(obj: object, spine: Spine, seen: Optional[set] = None) -> None:
    if seen is None:
        seen = set()

    if isinstance(obj, classes.PPtr):
        if obj.path_id == 0 and obj.file_id == 0:
            return
        if obj.path_id in seen:
            return
        seen.add(obj.path_id)
        try:
            obj = obj.read()
        except (AttributeError, FileNotFoundError):
            return

    if isinstance(obj, classes.MonoBehaviour):
        _record_spine_component(obj, spine)

    if isinstance(obj, classes.ComponentPair):
        crawl(obj.component, spine, seen)
    elif isinstance(obj, classes.Object):
        for k, v in obj.__dict__.items():
            if k == "m_Shader":
                continue  # don't descend into shader graphs
            crawl(v, spine, seen)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            crawl(item, spine, seen)
    elif isinstance(obj, dict):
        for item in obj.values():
            crawl(item, spine, seen)
    # Everything else (scalars, Vector*/Quaternionf/ColorRGBA, strings) is a
    # leaf with nothing to traverse.


def handle_skeleton(skeleton_object: classes.GameObject):
    spine = SpineInfo("<unknown>", skeleton_object.m_Name)
    spine.ids.add(_path_id(skeleton_object))

    for obj in (_component_ptr(x).read() for x in skeleton_object.m_Component):
        spine.ids.add(_path_id(obj))

        if isinstance(obj, classes.RectTransform):
            pos = obj.m_LocalPosition
            scale = obj.m_LocalScale
            pivot = obj.m_Pivot
            assert pos is not None and scale is not None and pivot is not None
            spine.position = (pos.x, pos.y)
            spine.set_scale(scale.x)
            spine.pivot = (pivot.x, pivot.y)
            spine.transform_id = _path_id(obj)
            if obj.m_Father is not None and obj.m_Father.path_id != 0:
                father = obj.m_Father.read()
                if isinstance(father, classes.RectTransform):
                    father_pos = father.m_LocalPosition
                    assert father_pos is not None
                    spine.position = (
                        pos.x + father_pos.x,
                        pos.y + father_pos.y,
                    )
        else:
            sort_order: Optional[int] = getattr(obj, "m_SortingOrder", None)
            if sort_order is not None:
                spine.order = sort_order

        if not isinstance(obj, classes.MonoBehaviour):
            continue

        script_type = obj.m_Script.read().m_ClassName
        if script_type in ("SkeletonGraphic", "SkeletonAnimation"):
            sk = _script(obj, _SkeletonGraphic)
            # Try get the texture from the material, this is one route, the other is through the atlas assets
            if hasattr(obj, "m_Material") and sk.m_Material.path_id != 0:
                tex = texture_from_material(sk.m_Material.read())
                if tex is not None:
                    spine.textures.append(tex)

            if hasattr(obj, "_animationName"):
                spine.default_animation = getattr(obj, "_animationName")

            skeleton_data_asset = sk.skeletonDataAsset.read()

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


def handle_bone_follower(obj: classes.MonoBehaviour):
    follower_script = _script(obj, _BoneFollowerGraphic)
    bone_follower = BoneFollower(
        follower_script.boneName,
        follower_script.skeletonGraphic.read()
        .skeletonDataAsset.read()
        .skeletonJSON.read()
        .m_Name,
    )

    for child in walk_object_children(obj.m_GameObject):
        if isinstance(child, classes.RectTransform):
            bone_follower.transforms.add(_path_id(child))

    return bone_follower


def walk_object_children(obj: object):
    """
    Walks through an object, but only uses known *descendant* properties, rather than trying to go every which way up and down
    :param obj: Unity game object
    :return: yields all objects it passes that arent PPtr's or ComponentPair's
    """
    seen = set()
    queue: list[Any] = [obj]

    while queue:
        current = queue.pop(0)
        if isinstance(current, classes.PPtr):
            if current.path_id == 0 and current.file_id == 0:
                continue

            if current.path_id in seen:
                continue
            seen.add(current.path_id)

            try:
                current = current.read()
            except AttributeError:
                continue
            except FileNotFoundError:
                continue

        node: Any = current
        if isinstance(node, classes.ComponentPair):
            queue.append(node.component)
            continue

        yield node

        if hasattr(node, "m_Children"):
            queue.extend(node.m_Children)
        if hasattr(node, "m_Component"):
            queue.extend(node.m_Component)


def check_global_scale(obj: classes.Object):
    if not isinstance(obj, classes.GameObject):
        return None, None

    for entry in obj.m_Component:
        c = _component_ptr(entry).read()
        if isinstance(c, classes.RectTransform) or isinstance(c, classes.Transform):
            local_scale = c.m_LocalScale
            assert local_scale is not None
            scale, pid = local_scale.x, {_path_id(c)}
            children = c.m_Children
            if (
                children is not None
                and len(children) == 1
                and children[0].type == ClassIDType.RectTransform
            ):
                pid.add(children[0].path_id)
                child = children[0].read()
                child_scale = child.m_LocalScale
                assert child_scale is not None
                extra_scale = child_scale.x
                if extra_scale > 2:
                    extra_scale /= 100
                scale *= extra_scale
            return scale, pid
    return None, None


def extract_spine(
    name: str, obj: list[classes.Object], output_dir: str, write_json=False
):
    spine = Spine(name)

    last_obj = obj[-1] if obj else None
    for o in obj:
        crawl(o, spine)

    if last_obj is not None:
        global_scale, gs_pid = check_global_scale(last_obj)
        if gs_pid is not None:
            assert global_scale is not None
            if global_scale > 2:
                global_scale /= 100
            logger.debug(f"found global scale {global_scale} at path {gs_pid}")
            if global_scale != 1:
                if any(x.transform_id in gs_pid for x in spine.spines):
                    logger.debug("Found spine with global scale, skipping")
                else:
                    for spine_info in spine.spines:
                        spine_info.scale *= global_scale

    spine.finalize()
    apply_quirk(spine)

    if len(spine.spines) > 0:
        spine.write(output_dir)
    else:
        logger.debug(f"Processed {name} but no spines found")

    if write_json and last_obj is not None:
        json_dir = os.path.join(output_dir, name)
        os.makedirs(json_dir, exist_ok=True)
        with open(os.path.join(json_dir, "jsonified.json"), "w") as f:
            json.dump(
                jsonify(last_obj),
                f,
                indent=4,
                default=lambda x: f"<unserializable {type(x).__name__}>",
            )
