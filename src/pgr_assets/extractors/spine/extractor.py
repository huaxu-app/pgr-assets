import json
import logging
import os

from UnityPy import classes
from UnityPy.enums import ClassIDType
from typing import Optional

from .quirks import apply_quirk
from .models import Spine, BoneFollower, SpineInfo
from pgr_assets.converters.unity_to_json import jsonify

logger = logging.getLogger('spine-extractor')

def texture_from_material(mat: classes.Material):
    for (name, tex_env) in mat.m_SavedProperties.m_TexEnvs:
        if name == '_MainTex':
            if tex_env.m_Texture.path_id == 0:
                return None
            t = tex_env.m_Texture.read()
            return t.m_Name, t.image
    return None

def flatten(l):
    for el in l:
        if isinstance(el, (list, tuple)):
            yield from flatten(el)
        elif isinstance(el, dict):
            yield from flatten(el.values())
        else:
            yield el

def crawl(obj: classes.Object, spine: Spine, seen: Optional[set] = None):
    if seen is None:
        seen = set()

    if isinstance(obj, classes.PPtr):
        if obj.path_id == 0 and obj.file_id == 0:
            return None

        if obj.path_id in seen:
            return f'<seen {obj.path_id}>'
        seen.add(obj.path_id)

        try:
            obj = obj.read()
        except AttributeError:
            return None
        except FileNotFoundError:
            return None


    if isinstance(obj, classes.MonoBehaviour):
        script = obj.m_Script.read()

        if script.m_ClassName in ('SkeletonGraphic', 'SkeletonAnimation'):
            go = obj.m_GameObject.read()
            if go.m_IsActive:
                spine.spines.append(handle_skeleton(go))
        elif script.m_ClassName == 'BoneFollowerGraphic':
            follower = handle_bone_follower(obj)
            spine.bone_followers.append(follower)
        elif script.m_ClassName == 'UiObject':
            logger.debug("Got UiObject -> likely Movie Spine")
            spine.spine_order_list = [x.path_id for x in obj.ObjList]
            spine.found_size = (1000, 1080)
        elif script.m_ClassName == 'XEffectScaler':
            spine.found_size = (round(obj.DesignWidth), round(obj.DesignHeight))

    if isinstance(obj, classes.ComponentPair):
        return {
            '__type': type(obj).__name__,
            'component': crawl(obj.component, spine, seen)
        }
    elif isinstance(obj, classes.Object):
        ret = {
            '__type': type(obj).__name__,
        }
        if obj.object_reader is not None:
            ret['__path_id'] = obj.object_reader.path_id
        for k, v in obj.__dict__.items():
            if k == 'm_Shader':
                v = None

            if isinstance(v, (list, tuple)):
                v = [crawl(subv, spine, seen) for subv in flatten(v)]
            elif isinstance(v, dict):
                v = {subk: crawl(subv, spine, seen) for subk, subv in v.items()}

            ret[k] = crawl(v, spine, seen)
        return ret

    elif isinstance(obj, classes.Vector2f):
        return [obj.x, obj.y]
    elif isinstance(obj, classes.Vector3f):
        return [obj.x, obj.y, obj.z]
    elif isinstance(obj, classes.Vector4f):
        return [obj.x, obj.y, obj.z, obj.w]
    elif isinstance(obj, classes.Quaternionf):
        return [obj.x, obj.y, obj.z, obj.w]
    elif isinstance(obj, classes.ColorRGBA):
        return 'rgba(%d, %d, %d, %d)' % (obj.r, obj.g, obj.b, obj.a)
    return obj


def handle_skeleton(skeleton_object: classes.MonoBehaviour):
    spine = SpineInfo("<unknown>", skeleton_object.m_Name)
    spine.ids.add(skeleton_object.object_reader.path_id)

    for obj in (x.component.read() for x in skeleton_object.m_Component):
        spine.ids.add(obj.object_reader.path_id)

        if isinstance(obj, classes.RectTransform):
            spine.position = (obj.m_LocalPosition.x, obj.m_LocalPosition.y)
            spine.set_scale(obj.m_LocalScale.x)
            spine.pivot = (obj.m_Pivot.x, obj.m_Pivot.y)
            spine.transform_id = obj.object_reader.path_id
            if obj.m_Father is not None and obj.m_Father.path_id != 0:
                father = obj.m_Father.read()
                if isinstance(father, classes.RectTransform):
                    spine.position = (spine.position[0] + father.m_LocalPosition.x, spine.position[1] + father.m_LocalPosition.y)
        elif (sortOrder := getattr(obj, 'm_SortingOrder', None)) is not None:
            spine.order = sortOrder

        if not isinstance(obj, classes.MonoBehaviour):
            continue

        script_type = obj.m_Script.read().m_ClassName
        if script_type in ('SkeletonGraphic', 'SkeletonAnimation'):
            # Try get the texture from the material, this is one route, the other is through the atlas assets
            if hasattr(obj, 'm_Material') and obj.m_Material.path_id != 0:
                tex = texture_from_material(obj.m_Material.read())
                if tex is not None:
                    spine.textures.append(tex)

            if hasattr(obj, '_animationName'):
                spine.default_animation = obj._animationName

            skeleton_data_asset = obj.skeletonDataAsset.read()

            skeleton_json = skeleton_data_asset.skeletonJSON.read()
            spine.name = skeleton_json.m_Name
            spine.json = skeleton_json.m_Script

            atlas_asset = skeleton_data_asset.atlasAssets[0].read()
            spine.atlas = atlas_asset.atlasFile.read().m_Script
            for mat in atlas_asset.materials:
                tex = texture_from_material(mat.read())
                if tex is not None:
                    spine.textures.append(tex)
        elif script_type == 'XEffectScaler':
            spine.size = (round(obj.DesignWidth), round(obj.DesignHeight))


    if spine.valid():
        logger.debug(f"Found spine: {spine}")
        return spine
    else:
        logger.warning(f"Invalid spine: {spine}")

def handle_bone_follower(obj: classes.MonoBehaviour):
    bone_follower = BoneFollower(obj.boneName, obj.skeletonGraphic.read().skeletonDataAsset.read().skeletonJSON.read().m_Name)

    for obj in walk_object_children(obj.m_GameObject):
        if isinstance(obj, classes.RectTransform):
            bone_follower.transforms.add(obj.object_reader.path_id)

    return bone_follower

def walk_object_children(obj: classes.Object):
    """
    Walks through an object, but only uses known *descendant* properties, rather than trying to go every which way up and down
    :param obj: Unity game object
    :return: yields all objects it passes that arent PPtr's or ComponentPair's
    """
    seen = set()
    queue = [obj]

    while queue:
        obj = queue.pop(0)
        if isinstance(obj, classes.PPtr):
            if obj.path_id == 0 and obj.file_id == 0:
                continue

            if obj.path_id in seen:
                continue
            seen.add(obj.path_id)

            try:
                obj = obj.read()
            except AttributeError:
                continue
            except FileNotFoundError:
                continue

        if isinstance(obj, classes.ComponentPair):
            queue.append(obj.component)
            continue

        yield obj

        if hasattr(obj, 'm_Children'):
            queue.extend(obj.m_Children)
        if hasattr(obj, 'm_Component'):
            queue.extend(obj.m_Component)

def check_global_scale(obj: classes.Object):
    if not isinstance(obj, classes.GameObject):
        return None, None

    for c in obj.m_Component:
        c = c.component.read()
        if isinstance(c, classes.RectTransform) or isinstance(c, classes.Transform):
            scale, pid = c.m_LocalScale.x, {c.object_reader.path_id}
            if len(c.m_Children) == 1 and c.m_Children[0].type == ClassIDType.RectTransform:
                pid.add(c.m_Children[0].path_id)
                extra_scale = c.m_Children[0].read().m_LocalScale.x
                if extra_scale > 2:
                    extra_scale /= 100
                scale *= extra_scale
            return scale, pid
    return None, None

def extract_spine(name: str, obj: list[classes.Object], output_dir: str, write_json=False):
    spine = Spine(name)

    for obj in obj:
        crawl(obj, spine)

    global_scale, gs_pid = check_global_scale(obj)
    if gs_pid is not None:
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

    if write_json:
        os.makedirs(f'{output_dir}/{name}', exist_ok=True)
        with open(f'{output_dir}/{name}/jsonified.json', 'w') as f:
            json.dump(jsonify(obj), f, indent=4, default=lambda x: f'<unserializable {type(x).__name__}>')
