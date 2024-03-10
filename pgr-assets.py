import argparse
import logging
import sys
import UnityPy

import extractors
from sources import SourceSet

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('pgr-assets')

DECRYPTION_KEY = 'y5XPvqLOrCokWRIa'


def process_bundle(bundle: str, sources: SourceSet, output_dir: str):
    bundle_data = sources.find_bundle(bundle)
    env = UnityPy.load(bundle_data)
    logger.info(f"Extracting {bundle}")
    extractors.extract_bundle(env, output_dir=output_dir)


def main():
    parser = argparse.ArgumentParser(description='Extracts the assets required for kennel')
    parser.add_argument('--primary', type=str, choices=['obb', 'EN_PC', 'CN_PC'], default='EN_PC')
    parser.add_argument('--obb', type=str, help='Path to obb file. Only valid when --primary is set to obb.')
    parser.add_argument('--patch', type=str, choices=['EN', 'EN_PC', 'KR', 'CN_PC'], default='EN_PC')
    parser.add_argument('--version', type=str, help='The client version to use.', required=True)
    parser.add_argument('--output', type=str, help='Output directory to use', required=True)
    parser.add_argument('--decrypt-key', type=str, help='Decryption key to use', default=DECRYPTION_KEY)
    parser.add_argument('--list', action='store_true', help='List all available bundles')
    parser.add_argument('bundles', nargs='*', help='Bundles to extract')
    args = parser.parse_args()

    if len(args.bundles) == 0 and not args.list:
        parser.error('No bundles specified')

    UnityPy.set_assetbundle_decrypt_key(args.decrypt_key)

    ss = SourceSet()
    ss.add_primary(args.version, args.primary, args.obb)
    ss.add_patch(args.patch, args.version)

    if args.list:
        print("Available bundles:")
        for bundle in ss.list_all_bundles():
            print(f" - {bundle}")
        sys.exit(0)

    for bundle in args.bundles:
        if bundle.endswith('.ab'):
            process_bundle(bundle, ss, args.output)
        elif bundle.endswith('.awb'):
            pass
            # process_audio(bundle, [primary_source, patch_source], args.output)


if __name__ == '__main__':
    main()
