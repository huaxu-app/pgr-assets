import argparse
from dataclasses import dataclass
from typing import Iterable, List, Literal, Optional, Sequence, Set

import UnityPy
from tap import Tap

from pgr_assets.asset_paths import TEMP_BUNDLE_MARKER, TEXTURE_BUNDLE_MARKER
from pgr_assets.sources import SourceSet
from pgr_assets.versions import parse_version

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

    def configure(self) -> None:
        # Accept --log-level after the subcommand too; SUPPRESS stops the subparser
        # default from clobbering a value given before the subcommand.
        self.add_argument(
            "--log-level",
            default=argparse.SUPPRESS,
            help="Set log verbosity (e.g. debug, info, warning)",
        )


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
        super().configure()
        self.add_argument("bundles", nargs="*", help="Bundles to extract")


def selected_bundles(args: BundleCommandArgs, ss: SourceSet) -> Set[str]:
    """Resolve the explicit bundle names plus everything matched by the
    ``--all*`` flags into a deduplicated set.
    """
    listed = set(args.bundles)
    listed.update(
        bundle
        for bundle in ss.list_all_bundles()
        if args.all
        or (args.all_temp and bundle.endswith(".ab") and TEMP_BUNDLE_MARKER in bundle)
        or (
            args.all_images
            and bundle.endswith(".ab")
            and TEXTURE_BUNDLE_MARKER in bundle
        )
        or (args.all_audio and bundle.endswith(".acb"))
        or (args.all_video and bundle.endswith(".usm"))
    )
    return listed


HIGHLIGHT = "\033[01;31m"  # bold red, matching grep's default
RESET = "\033[0m"


def filter_bundles(bundles: Iterable[str], patterns: Sequence[str]) -> List[str]:
    """Sort bundles; with patterns, keep those matching every one as a
    case-insensitive substring of the full path (AND-combined)."""
    ordered = sorted(bundles)
    if not patterns:
        return ordered
    needles = [p.lower() for p in patterns]
    return [b for b in ordered if all(n in b.lower() for n in needles)]


def highlight(text: str, patterns: Sequence[str]) -> str:
    """Wrap every case-insensitive match of any pattern in ANSI color, grep-style.
    Overlapping matches are merged so codes never nest."""
    lowered = text.lower()
    spans: List[tuple[int, int]] = []
    for p in patterns:
        needle = p.lower()
        start = lowered.find(needle) if needle else -1
        while start >= 0:
            spans.append((start, start + len(needle)))
            start = lowered.find(needle, start + len(needle))
    if not spans:
        return text

    spans.sort()
    merged = [spans[0]]
    for s, e in spans[1:]:
        if s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    out: List[str] = []
    prev = 0
    for s, e in merged:
        out.append(text[prev:s])
        out.append(HIGHLIGHT + text[s:e] + RESET)
        prev = e
    out.append(text[prev:])
    return "".join(out)


def determine_decryption_key(version: tuple[int, ...]) -> str:
    for check_version, key in DECRYPTION_KEYS:
        if version >= check_version:
            return key
    return ""


@dataclass
class ResolvedSources:
    """Outcome of :func:`build_source_set`: the configured source set plus the
    resolved game version and the asset-bundle decryption key that was applied."""

    sources: SourceSet
    version: tuple[int, ...]
    decrypt_key: str


def _apply_decrypt_key(version: tuple[int, ...], override: Optional[str]) -> str:
    """Pick the decryption key (an explicit override wins, otherwise it's derived
    from the version) and apply it to UnityPy's process-global state. Returns the
    key so worker processes that need to re-apply it can be handed the value."""
    key = override if override is not None else determine_decryption_key(version)
    UnityPy.set_assetbundle_decrypt_key(key)
    return key


def build_source_set(args: BaseArgs) -> ResolvedSources:
    # Default to global when no source is specified; --primary/--patch opts out.
    if args.preset is None and args.primary is None and args.patch is None:
        args.preset = "global"

    primary = PRESETS[args.preset] if args.preset is not None else args.primary
    patch = PRESETS[args.preset] if args.preset is not None else args.patch

    if primary is None:
        raise ValueError("No primary source specified (use --preset or --primary)")
    if args.obb is not None and args.version is None:
        raise ValueError(
            "Version must be specified when using an obb file as the primary source"
        )

    source_set = SourceSet()

    # When the version is known up front (always so for OBB), resolve and apply
    # the decrypt key *before* add_primary, since reading an OBB index bundle
    # needs it. Otherwise the version is inferred from the primary source below.
    explicit_version = parse_version(args.version) if args.version is not None else None
    decrypt_key: Optional[str] = None
    if explicit_version is not None:
        decrypt_key = _apply_decrypt_key(explicit_version, args.decrypt_key)

    source_set.add_primary(primary, args.obb, args.prerelease)

    version = explicit_version
    if version is None:
        inferred = source_set.version()
        assert inferred is not None, "could not determine version from primary source"
        version = inferred[:3]
    if decrypt_key is None:
        decrypt_key = _apply_decrypt_key(version, args.decrypt_key)

    if patch is not None:
        source_set.add_patch(patch, args.version)

    if not decrypt_key:
        raise RuntimeError(
            "No decryption key was able to be determined. Specify manually!"
        )

    return ResolvedSources(source_set, version, decrypt_key)
