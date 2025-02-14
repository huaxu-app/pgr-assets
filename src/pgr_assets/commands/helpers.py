from typing import Optional, Literal

import UnityPy
from tap import Tap

from pgr_assets.sources import SourceSet

DECRYPTION_KEY = 'y5XPvqLOrCokWRIa'
OLD_DECRYPTION_KEY = 'kurokurokurokuro'

PRESETS = {
    'global': 'EN_PC',
    'korea': 'KR_PC',
    'japan': 'JP_PC',
    'taiwan': 'TW_PC',
    'china': 'CN_PC',
    'china-beta': 'CN_PC_BETA',
}

class BaseArgs(Tap):
    preset: Optional[Literal['global', 'korea', 'japan', 'taiwan', 'china', 'china-beta']] = None # Preset to use for primary and patch
    prerelease: bool = False # Use the prerelease patch source, if available

    primary: Optional[Literal['obb', 'EN_PC', 'KR_PC', 'JP_PC', 'TW_PC', 'CN_PC', 'CN_PC_BETA']] = None # Primary source to use
    obb: Optional[str] = None # Path to obb file. Only valid when primary is set to obb
    patch: Optional[Literal['EN', 'EN_PC', 'KR', 'KR_PC', 'JP', 'JP_PC', 'TW', 'TW_PC', 'CN', 'CN_PC', 'CN_PC_BETA']] = None # Patch source to use
    version: Optional[str] = None # The client version to use. Inferred by default

    decrypt_key: str = DECRYPTION_KEY # Decryption key to use for asset bundles

def build_source_set(args: BaseArgs) -> SourceSet:
    UnityPy.set_assetbundle_decrypt_key(args.decrypt_key)

    primary = args.primary
    if args.preset is not None:
        primary = PRESETS[args.preset]

    patch = args.patch
    if args.preset is not None:
        patch = PRESETS[args.preset]

    if patch is None:
        raise ValueError('Patch source must be specified')

    if args.obb is not None and args.version is None:
        raise ValueError('Version must be specified when using an obb file as the primary source')

    source_set = SourceSet()
    source_set.add_primary(primary, args.obb, args.prerelease)
    source_set.add_patch(patch, args.version)

    return source_set
