# text-asset container path that holds binary tables / lua
# (e.g. "assets/temp/bytes/share/...").
TEMP_BYTES_MARKER = "/temp/bytes/"

# Image trees that get an extra thumbnail alongside the full-size output.
# The trailing slash keeps "/image/rolestoryface/" out of the set.
THUMBNAIL_IMAGE_MARKERS = ("/image/rolecharacter/", "/image/rolestory/")
THUMBNAIL_SIZE = 256

# Bundle-name markers used by the --all-temp / --all-images selection filters.
TEMP_BUNDLE_MARKER = "assets/temp/"
TEXTURE_BUNDLE_MARKER = "assets/product/texture/"

# Location of spine prefabs within the Unity environment.
SPINE_PREFAB_PREFIX = "assets/product/ui/spine/"

# Substring identifying spine-related bundles to mirror into the env dir.
SPINE_BUNDLE_MARKER = "spine"
