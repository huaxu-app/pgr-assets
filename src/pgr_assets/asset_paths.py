# text-asset container path that holds binary tables / lua
# (e.g. "assets/temp/bytes/share/...").
TEMP_BYTES_MARKER = "/temp/bytes/"

# Image trees that get an extra thumbnail alongside the full-size output, mapped
# to the size that tree is scaled to fit. The trailing slash keeps
# "/image/rolestoryface/" out of the set. The 480 trees are landscape artwork
# shown in dense grids, where 256 would only be 144 tall; 480 covers a ~240px
# tile at 2x DPR.
THUMBNAIL_IMAGE_SIZES = {
    "/image/rolecharacter/": 256,
    "/image/rolestory/": 256,
    "/image/bgcg/": 480,
    "/image/bgstory/": 480,
    "/image/bgui/": 480,
    "/image/uiarchivestorybanner/": 480,
    "/image/uidlcmultiplayer/": 480,
    "/image/uipicturepuzzle/": 480,
    "/image/bgcomiccg/": 480,
}

# Trees whose art ships as a stretched power-of-two texture: the file is
# 2048x1024 but the client draws it at the aspect the table declares. Thumbnails
# here are resampled to the true aspect instead of inheriting the file's, so the
# thumb is right on its own. 244 of bgcomiccg's 290 files are that stretch, and
# every one is 16:9 once drawn. Not bgcg, whose aspects are genuinely varied.
THUMBNAIL_FORCED_ASPECTS = {
    "/image/bgcomiccg/": 16 / 9,
}

# Bundle-name markers used by the --all-temp / --all-images selection filters.
TEMP_BUNDLE_MARKER = "assets/temp/"
TEXTURE_BUNDLE_MARKER = "assets/product/texture/"

# Location of spine prefabs within the Unity environment.
SPINE_PREFAB_PREFIX = "assets/product/ui/spine/"

# Substring identifying spine-related bundles to mirror into the env dir.
SPINE_BUNDLE_MARKER = "spine"
