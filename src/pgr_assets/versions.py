# The patch CDN URL scheme changed in 4.3.0 ("A Better Tomorrow"): from this
# version onward a per-build key segment is inserted into the config/patch URLs.
PATCH_KEY_SCHEME_MIN_VERSION = (4, 3, 0)


def parse_version(version: str) -> tuple[int, ...]:
    """Parse a dotted version string like ``"4.3.0"`` into a tuple of ints."""
    return tuple(int(part) for part in version.split("."))
