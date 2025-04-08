import logging
from typing import Optional, Literal

import UnityPy
from UnityPy.enums import ArchiveFlags
from tap import Tap

from pgr_assets.sources import SourceSet

VERSION_BAD_ENCRYPT = (3, 4, 0)
DECRYPTION_KEYS = [
    ((3, 4, 0), 'XxecodrPeGaka2e6'),
    ((1, 22, 0), 'y5XPvqLOrCokWRIa'),
    ((0, 0, 0), 'kurokurokurokuro'),
]

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
    patch: Optional[Literal['EN', 'EN_PC', 'KR', 'KR_PC', 'JP', 'JP_PC', 'TW', 'TW_PC', 'CN', 'CN_PC', 'CN_PC_BETA', 'CN_BETA']] = None # Patch source to use
    version: Optional[str] = None # The client version to use. Inferred by default

    decrypt_key: Optional[str] = None # Decryption key to use for asset bundles

def determine_decryption_key(version: tuple[int, ...]) -> str:
    for check_version, key in DECRYPTION_KEYS:
        if version >= check_version:
            return key
    return ''

def build_source_set(args: BaseArgs) -> SourceSet:
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

    version = None
    # Preliminary version hacks for OBB based extraction
    if args.version is not None and args.decrypt_key is None:
        version = tuple([int(x) for x in args.version.split('.')])
        args.decrypt_key = determine_decryption_key(version)
        UnityPy.set_assetbundle_decrypt_key(args.decrypt_key)
        patch_unitypy_encryption(version)

    source_set = SourceSet()
    source_set.add_primary(primary, args.obb, args.prerelease)

    # Primary source (non OBB, but defended against above) has a JSON-only route to a version number.
    # Use this to determine key
    if args.version is None and args.decrypt_key is None:
        version = source_set.version()[:3]
        args.decrypt_key = determine_decryption_key(version)
        UnityPy.set_assetbundle_decrypt_key(args.decrypt_key)

    patch_unitypy_encryption(version)

    source_set.add_patch(patch, args.version)

    if args.decrypt_key is None:
        raise RuntimeError("No decryption key was able to be determined. Specify manually!")

    return source_set

def patch_unitypy_encryption(version: tuple[int, ...]) -> None:
    """
    Newer versions of Unity (2022.3.52f1c1) changes the encryption flag from 0x200 to 0x400,
    but asset bundles from PGR continue to use the old 0x200 value.

    Hackily assign new value to the enum inside the library.

    I'm sorry this is necessary
    :return:
    """
    from UnityPy.enums.BundleFile import ArchiveFlags

    if version < VERSION_BAD_ENCRYPT or ArchiveFlags.UsesAssetBundleEncryption.value == 0x200:
        return

    # I must _again_ warn against how horrible this idea is
    _change_enum_value(ArchiveFlags.UsesAssetBundleEncryption.value, 0x200)

# https://stackoverflow.com/questions/74909582/is-it-possible-to-change-the-attribute-value-in-the-enum
def _change_enum_value(old: object, new: object) -> None:
    """
     Assigns contents of new object to old object.
     The size of new and old objection should be identical.

     Args:
         old (Any): Any object
         new (Any): Any object
     Raises:
         ValueError: Size of objects don't match
     Faults:
         Segfault: OOB write on destination
     """
    from sys import getsizeof
    from ctypes import c_byte

    src_s, des_s = getsizeof(new), getsizeof(old)
    if src_s != des_s:
        raise ValueError("Size of new and old objects don't match")
    src_arr = (c_byte * src_s).from_address(id(new))
    des_arr = (c_byte * des_s).from_address(id(old))
    for index in range(len(des_arr)):
        des_arr[index] = src_arr[index]