from typing import List, Literal, Optional, Set

import UnityPy
from tap import Tap

from pgr_assets.asset_paths import TEMP_BUNDLE_MARKER, TEXTURE_BUNDLE_MARKER
from pgr_assets.sources import SourceSet

VERSION_BAD_ENCRYPT = (3, 4, 0)
DECRYPTION_KEYS = [
    ((3, 4, 0), "XxecodrPeGaka2e6"),
    ((1, 22, 0), "y5XPvqLOrCokWRIa"),
    ((0, 0, 0), "kurokurokurokuro"),
]

PRESETS = {
    "global": "EN_PC",
    "korea": "KR_PC",
    "japan": "JP_PC",
    "taiwan": "TW_PC",
    "china": "CN_PC",
    "china-beta": "CN_PC_BETA",
}


class BaseArgs(Tap):
    preset: Optional[
        Literal["global", "korea", "japan", "taiwan", "china", "china-beta"]
    ] = None  # Preset to use for primary and patch
    prerelease: bool = False  # Use the prerelease patch source, if available

    primary: Optional[
        Literal["obb", "EN_PC", "KR_PC", "JP_PC", "TW_PC", "CN_PC", "CN_PC_BETA"]
    ] = None  # Primary source to use
    obb: Optional[str] = None  # Path to obb file. Only valid when primary is set to obb
    patch: Optional[
        Literal[
            "EN",
            "EN_PC",
            "KR",
            "KR_PC",
            "JP",
            "JP_PC",
            "TW",
            "TW_PC",
            "CN",
            "CN_PC",
            "CN_PC_BETA",
            "CN_BETA",
        ]
    ] = None  # Patch source to use
    version: Optional[str] = None  # The client version to use. Inferred by default

    decrypt_key: Optional[str] = None  # Decryption key to use for asset bundles


class BundleCommandArgs(BaseArgs):
    """Shared flags and selection logic for commands that operate on a chosen
    set of bundles and write them to an output directory (``extract``/``bundles``)."""

    output: str  # Output directory to use.

    all_temp: bool = False  # Extract all temp (text) bundles
    all_audio: bool = False  # Extract all audio bundles
    all_video: bool = False  # Extract all video bundles
    all_images: bool = False  # Extract all image bundles
    all: bool = False  # Extract all I can find

    bundles: List[str]  # Bundles to extract

    def configure(self) -> None:
        self.add_argument("bundles", nargs="*", help="Bundles to extract")

    def selected_bundles(self, ss: SourceSet) -> Set[str]:
        """Resolve the explicit bundle names plus everything matched by the
        ``--all*`` flags into a deduplicated set."""
        listed = set(self.bundles)
        listed.update(
            bundle
            for bundle in ss.list_all_bundles()
            if self.all
            or (self.all_temp and bundle.endswith(".ab") and TEMP_BUNDLE_MARKER in bundle)
            or (
                self.all_images
                and bundle.endswith(".ab")
                and TEXTURE_BUNDLE_MARKER in bundle
            )
            or (self.all_audio and bundle.endswith(".acb"))
            or (self.all_video and bundle.endswith(".usm"))
        )
        return listed


def determine_decryption_key(version: tuple[int, ...]) -> str:
    for check_version, key in DECRYPTION_KEYS:
        if version >= check_version:
            return key
    return ""


def build_source_set(args: BaseArgs) -> SourceSet:
    primary = args.primary
    if args.preset is not None:
        primary = PRESETS[args.preset]

    patch = args.patch
    if args.preset is not None:
        patch = PRESETS[args.preset]

    if args.obb is not None and args.version is None:
        raise ValueError(
            "Version must be specified when using an obb file as the primary source"
        )

    version = None
    # Preliminary version hacks for OBB based extraction
    if args.version is not None and args.decrypt_key is None:
        version = tuple([int(x) for x in args.version.split(".")])
        args.decrypt_key = determine_decryption_key(version)
        UnityPy.set_assetbundle_decrypt_key(args.decrypt_key)

    source_set = SourceSet()
    if primary is None:
        raise ValueError("No primary source specified (use --preset or --primary)")
    source_set.add_primary(primary, args.obb, args.prerelease)

    # Primary source (non OBB, but defended against above) has a JSON-only route to a version number.
    # Use this to determine key
    if args.version is None and args.decrypt_key is None:
        inferred = source_set.version()
        assert inferred is not None
        version = inferred[:3]
        args.decrypt_key = determine_decryption_key(version)
        UnityPy.set_assetbundle_decrypt_key(args.decrypt_key)

    if patch is not None:
        source_set.add_patch(patch, args.version)

    if args.decrypt_key is None:
        raise RuntimeError(
            "No decryption key was able to be determined. Specify manually!"
        )

    return source_set
