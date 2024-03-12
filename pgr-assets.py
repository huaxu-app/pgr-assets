import argparse
import concurrent.futures
import json
import logging
import os
import sys
from typing import Set, List, Generator

import UnityPy
from tqdm.auto import tqdm

import extractors
import extractors.bundle
from audio import CueRegistry, ACB
from sources import SourceSet

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('pgr-assets')

DECRYPTION_KEY = 'y5XPvqLOrCokWRIa'
AUDIO_KEY = 62855594017927612


class State:
    output_dir: str
    sources: SourceSet
    cues: CueRegistry

    def __init__(self, sources: SourceSet, output_dir: str):
        self.sources = sources
        self.cues = CueRegistry()
        self.output_dir = output_dir

    def load_cues(self):
        self.cues.init(self.sources)


def process_bundle(bundle: str, state: State):
    bundle_data = state.sources.find_bundle(bundle)
    env = UnityPy.load(bundle_data)
    logger.debug(f"Extracting {bundle}")
    extractors.bundle.extract_bundle(env, output_dir=state.output_dir)


def process_audio(bundle: str, state: State):
    cue_sheet = state.cues.get_cue_sheet(bundle)
    acb_data = state.sources.find_bundle(cue_sheet.acb)
    awb_data = b''
    if cue_sheet.awb:
        awb_data = state.sources.find_bundle(cue_sheet.awb)
    acb = ACB(acb_data, awb_data)
    logger.debug(f"Extracting {cue_sheet.acb}")
    acb.extract(key=AUDIO_KEY, dirname=os.path.join(state.output_dir, 'audio', cue_sheet.base_name), encode=True)


def process_usm(bundle: str, state: State):
    filename = bundle.split('/', 2)[2].split('.')[0].lower() + '.mp4'
    data = state.sources.find_bundle(bundle)
    usm = extractors.PGRUSM(data, key=AUDIO_KEY)
    logger.debug(f"Extracting {filename}")
    usm.extract_video(os.path.join(state.output_dir, 'video', filename))


def process(bundle: str, state: State):
    if bundle.endswith('.ab'):
        process_bundle(bundle, state)
    elif bundle.endswith('.acb'):
        process_audio(bundle, state)
    elif bundle.endswith('.awb'):
        pass  # ignore awb files, they're extracted with the acb
    elif bundle.endswith('.usm'):
        process_usm(bundle, state)
    else:
        raise ValueError(f"Unsupported bundle type: {bundle}")

    # Processed files get returned for processing into bundle cache
    return bundle


def determine_sha1_cache_skip(file: str, bundles: Set[str], state: State) -> Set[str]:
    if not os.path.exists(file):
        return bundles

    with open(file, 'r') as f:
        cached = json.load(f)

    wanted = set()

    for bundle in bundles:
        if bundle in cached:
            if state.sources.bundle_sha1(bundle) == cached[bundle]:
                logger.debug(f"Skipping {bundle} due to cache")
                continue
        wanted.add(bundle)

    return wanted


def write_sha1_cache(file: str, bundles: List[str], state: State):
    entries = {}
    if os.path.exists(file):
        with open(file, 'r') as f:
            entries = json.load(f)

    entries.update({bundle: state.sources.bundle_sha1(bundle) for bundle in bundles})

    with open(file, 'w') as f:
        json.dump(entries, f)


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
    parser.add_argument('--all-images', action='store_true', help='Extract all image bundles')
    parser.add_argument('--all', action='store_true', help='Extract all i can find')
    parser.add_argument('--cache', type=str, help='Path to sha1 cache file', default='')
    parser.add_argument('bundles', nargs='*', help='Bundles to extract')
    args = parser.parse_args()

    UnityPy.set_assetbundle_decrypt_key(args.decrypt_key)

    ss = SourceSet()
    ss.add_primary(args.version, args.primary, args.obb)
    ss.add_patch(args.patch, args.version)

    if args.list:
        print("Available bundles:")
        for bundle in ss.list_all_bundles():
            print(f" - {bundle}")
        sys.exit(0)

    state = State(ss, args.output)
    if any(bundle.endswith('.acb') for bundle in args.bundles) or args.all_audio or args.all:
        state.load_cues()

    # determine all tasks based on flags, use set because we don't want duplicates
    listed_bundles = set(args.bundles)
    listed_bundles.update(bundle for bundle in ss.list_all_bundles() if args.all or
                          (args.all_images and bundle.endswith('.ab') and 'assets/product/texture/' in bundle) or
                          (args.all_audio and bundle.endswith('.acb')) or (args.all_video and bundle.endswith('.usm')))

    if len(listed_bundles) == 0:
        logger.error('No bundles specified')
        sys.exit(1)

    if args.cache:
        listed_bundles = determine_sha1_cache_skip(args.cache, listed_bundles, state)

    finished_bundles = list()

    with concurrent.futures.ProcessPoolExecutor() as executor:
        futures = [executor.submit(process, bundle, state) for bundle in listed_bundles]
        for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures)):
            try:
                result = future.result()
                if result:
                    finished_bundles.append(result)

                # Checkpoints for cache
                if args.cache and len(finished_bundles) % 100 == 0:
                    write_sha1_cache(args.cache, finished_bundles, state)
            except Exception as e:
                logger.error(f"Failed to process bundle: {e}")

    if args.cache:
        write_sha1_cache(args.cache, finished_bundles, state)


if __name__ == '__main__':
    main()
