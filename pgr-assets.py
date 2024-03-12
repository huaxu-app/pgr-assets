import argparse
import logging
import multiprocessing
import os
import sys
import UnityPy

import extractors
import extractors.bundle
from audio import CueRegistry, ACB
from sources import SourceSet

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('pgr-assets')

DECRYPTION_KEY = 'y5XPvqLOrCokWRIa'
AUDIO_KEY = 62855594017927612


class Lookups:
    sources: SourceSet
    cues: CueRegistry

    def __init__(self, sources: SourceSet):
        self.sources = sources
        self.cues = CueRegistry()

    def load_cues(self):
        self.cues.init(self.sources)


def process_bundle(bundle: str, state: Lookups, output_dir: str):
    bundle_data = state.sources.find_bundle(bundle)
    env = UnityPy.load(bundle_data)
    logger.info(f"Extracting {bundle}")
    extractors.bundle.extract_bundle(env, output_dir=output_dir)


def process_audio(bundle: str, state: Lookups, output_dir: str):
    cue_sheet = state.cues.get_cue_sheet(bundle)
    acb_data = state.sources.find_bundle(cue_sheet.acb)
    awb_data = b''
    if cue_sheet.awb:
        awb_data = state.sources.find_bundle(cue_sheet.awb)
    acb = ACB(acb_data, awb_data)
    logger.info(f"Extracting {cue_sheet.acb}")
    acb.extract(decode=True, key=AUDIO_KEY, dirname=os.path.join(output_dir, cue_sheet.base_name))


def process_usm(bundle: str, state: Lookups, output_dir: str):
    filename = os.path.splitext(bundle)[0] + '.mp4'
    data = state.sources.find_bundle(bundle)
    usm = extractors.PGRUSM(data, key=AUDIO_KEY)
    usm.extract_video(os.path.join(output_dir, filename))


def main():
    parser = argparse.ArgumentParser(description='Extracts the assets required for kennel')
    parser.add_argument('--primary', type=str, choices=['obb', 'EN_PC', 'CN_PC'], default='EN_PC')
    parser.add_argument('--obb', type=str, help='Path to obb file. Only valid when --primary is set to obb.')
    parser.add_argument('--patch', type=str, choices=['EN', 'EN_PC', 'KR', 'CN_PC'], default='EN_PC')
    parser.add_argument('--version', type=str, help='The client version to use.', required=True)
    parser.add_argument('--output', type=str, help='Output directory to use', required=True)
    parser.add_argument('--decrypt-key', type=str, help='Decryption key to use', default=DECRYPTION_KEY)
    parser.add_argument('--list', action='store_true', help='List all available bundles')
    parser.add_argument('--all-audio', action='store_true', help='Extract all audio bundles')
    parser.add_argument('--all-video', action='store_true', help='Extract all video bundles')
    parser.add_argument('bundles', nargs='*', help='Bundles to extract')
    args = parser.parse_args()

    if len(args.bundles) == 0 and not args.list and not args.all_audio and not args.all_video:
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

    state = Lookups(ss)
    if any(bundle.endswith('.acb') for bundle in args.bundles) or args.all_audio:
        state.load_cues()

    for bundle in args.bundles:
        if bundle.endswith('.ab'):
            process_bundle(bundle, state, args.output)
        elif bundle.endswith('.acb'):
            process_audio(bundle, state, args.output)
        elif bundle.endswith('.usm'):
            process_usm(bundle, state, args.output)

    if args.all_audio or args.all_video:
        for bundle in ss.list_all_bundles():
            if args.all_video and bundle.endswith('.usm'):
                process_usm(bundle, state, args.output)
            elif args.all_audio and bundle.endswith('.acb'):
                process_audio(bundle, state, args.output)


if __name__ == '__main__':
    main()
