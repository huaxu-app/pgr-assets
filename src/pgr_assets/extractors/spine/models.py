import os
import json
from typing import Tuple, List
from dataclasses import dataclass, field
from PIL import Image
from collections import Counter

@dataclass
class SpineInfo:
    name: str
    inner_name: str
    position: Tuple[float, float] | None = None
    size: Tuple[int, int] | None = None
    scale: float = 1
    pivot: Tuple[float, float] = (0.5, 0.5)

    order: int = 0
    ids: set[int] = field(default_factory=set)
    transform_id: int = 0
    default_animation: str | None = None

    textures: List[Tuple[str, Image]] = field(default_factory=list)
    atlas: str | None = None
    json: str | None = None

    extra: dict = field(default_factory=dict)

    def valid(self):
        return len(self.textures) > 0 and self.json is not None and self.atlas is not None

    def __repr__(self):
        return f"Spine({self.name} position={self.position} size={self.size} scale={self.scale} anchor={self.pivot} order={self.order} tf={self.transform_id})"

    def set_scale(self, scale: float):
        if scale > 2:
            scale /= 100
        self.scale = scale

    def to_json(self):
        return {
            "name": self.name,
            "innerName": self.inner_name,
            "position": self.position,
            "size": self.size,
            "scale": self.scale,
            "pivot": self.pivot,
            "extra": self.extra,
        }

    def write(self, output_dir: str):
        os.makedirs(output_dir, exist_ok=True)
        name = self.name
        if name.endswith('.skel'):
            name = self.name.removesuffix('.skel')
            with open(os.path.join(output_dir, name + '.skel'), 'wb') as f:
                f.write(self.json.encode('utf-8', 'surrogateescape'))
        else:
            with open(os.path.join(output_dir, name + '.json'), 'w') as f:
                f.write(self.json)
        with open(os.path.join(output_dir, name + '.atlas'), 'w') as f:
            f.write(self.atlas)
        for (name, image) in self.textures:
            image.save(os.path.join(output_dir, name.removeprefix(self.name + '_') + '.png'))

@dataclass
class BoneFollower:
    bone: str
    skeleton: str
    transforms: set[int] = field(default_factory=set)
    spines: set[str] = field(default_factory=set)

    def to_json(self):
        return {
            "bone": self.bone,
            "skeleton": self.skeleton,
            "spines": sorted(self.spines),
        }

@dataclass
class Spine:
    name: str
    spines: list[SpineInfo] = field(default_factory=list)
    spine_order_list: list[str]|None = None
    found_size: Tuple[int, int]|None = None
    bone_followers: list[BoneFollower] = field(default_factory=list)
    render_quirk: str|None = None

    def size(self):
        if self.found_size is not None:
            return self.found_size
        sizes = [x.size for x in self.spines if x.size is not None]
        if len(sizes) == 0:
            return None
        return max(x[0] for x in sizes), max(x[1] for x in sizes)

    def finalize(self):
        self.update_bone_followers()

        if self.spine_order_list is None:
            self.spines = sorted(self.spines, key=lambda x: x.order)
        else:
            self.fix_actor_spine()
            index = {x: i for i, x in enumerate(self.spine_order_list)}
            self.spines = sorted(self.spines, key=lambda x: min(index.get(p, float('inf')) for p in x.ids), reverse=True)

    def update_bone_followers(self):
        for follower in self.bone_followers:
            for spine in self.spines:
                if spine.transform_id in follower.transforms:
                    follower.spines.add(spine.name)
        self.bone_followers = [x for x in self.bone_followers if len(x.spines) > 0]

    def fix_actor_spine(self):
        if self.spine_order_list is None:
            return

        # First round of these was special
        if 'uimoviebiankaskin' in self.name:
            self.spine_order_list = self.spine_order_list[::-1]

        for spine in self.spines:
            # First round of these was special
            if 'uimoviebiankaskin' not in self.name:
                spine.position = (0, 0)
            spine.scale = 1
            spine.pivot = (0.5, 0)

    def to_json(self):
        obj = {
            "name": self.name,
            "spines": [x.to_json() for x in self.spines],
            "size": self.size(),
            "boneFollowers": [x.to_json() for x in self.bone_followers],
        }

        if self.render_quirk is not None:
            obj["renderQuirk"] = self.render_quirk

        animation_counts = Counter(x.default_animation for x in self.spines if x.default_animation is not None)
        if len(animation_counts) > 0:
            obj["defaultAnimation"] = animation_counts.most_common(1)[0][0]

        return obj

    def write(self, output_dir: str):
        subdir = os.path.join(output_dir, self.name)
        os.makedirs(subdir, exist_ok=True)
        with open(os.path.join(subdir, 'index.json'), 'w') as f:
            json.dump(self.to_json(), f, indent=4)
        for spine in self.spines:
            spine.write(subdir)

