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
    recode_video: bool
    nvenc: bool
    decrypt_key: str

    def __init__(self, sources: SourceSet, output_dir: str, decrypt_key: str, recode_video: bool = False, nvenc: bool = False):
        self.sources = sources
        self.cues = CueRegistry()
        self.output_dir = output_dir
        self.recode_video = recode_video
        self.nvenc = nvenc
        self.decrypt_key = decrypt_key

    def load_cues(self):
        self.cues.init(self.sources)


def process_bundle(bundle: str, state: State):
    bundle_data = state.sources.find_bundle(bundle)
    env = UnityPy.load(bundle_data)
    logger.debug(f"Extracting {bundle}")
    extractors.bundle.extract_bundle(env, output_dir=state.output_dir)


def process_audio(bundle: str, state: State):
    cue_sheet = state.cues.get_cue_sheet(bundle)

    awb_data = b''

    if cue_sheet is not None:
        acb_file = cue_sheet.acb
        base_name = cue_sheet.base_name
        acb_data = state.sources.find_bundle(cue_sheet.acb)
        if cue_sheet.awb:
            awb_data = state.sources.find_bundle(cue_sheet.awb)
    else:
        logger.warning(f"Failed to find cue sheet for {bundle}, making assumptions")
        acb_file = bundle
        base_name = bundle.split('/', 2)[2].split('.')[0].lower()
        acb_data = state.sources.find_bundle(bundle)
        try:
            awb_data = state.sources.find_bundle(bundle.replace('.acb', '.awb'))
        except Exception:
            pass

    acb = ACB(acb_data, awb_data)
    logger.debug(f"Extracting {acb_file}")
    acb.extract(key=AUDIO_KEY, dirname=os.path.join(state.output_dir, 'audio', base_name), encode=True)


def process_usm(bundle: str, state: State):
    filename = bundle.split('/', 2)[2].split('.')[0].lower() + '.mp4'
    data = state.sources.find_bundle(bundle)
    usm = extractors.PGRUSM(data, key=AUDIO_KEY)
    logger.debug(f"Extracting {filename}")
    usm.extract_video(os.path.join(state.output_dir, 'video', filename), recode=state.recode_video, nvenc=state.nvenc)


def process(bundle: str, state: State):
    UnityPy.set_assetbundle_decrypt_key(state.decrypt_key)
    try:
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
    except Exception as e:
        logger.exception(f"Failed to process {bundle}", exc_info=e)
        return None


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


def execute_in_pool(bundles: List[str], state: State, cache: str, max_workers: int = None, checkpoint_step: int = 100):
    finished_bundles = list()

    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process, bundle, state) for bundle in bundles]
        for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures)):
            try:
                result = future.result()
                if result:
                    finished_bundles.append(result)

                # Checkpoints for cache
                if cache and len(finished_bundles) % checkpoint_step == 0:
                    write_sha1_cache(cache, finished_bundles, state)
            except Exception as e:
                logger.error(f"Failed to process bundle: {e}")

    if cache:
        write_sha1_cache(cache, finished_bundles, state)

PRESETS = {
    'global': 'EN_PC',
    'korea': 'KR_PC',
    'japan': 'JP_PC',
    'taiwan': 'TW_PC',
    'china': 'CN_PC'
}

def main():
    parser = argparse.ArgumentParser(description='Extracts the assets required for kennel')
    parser.add_argument('--preset', type=str, choices=PRESETS.keys(), default='global')
    parser.add_argument('--prerelease', action='store_true', help='Use the prerelease patch source, if available')
    parser.add_argument('--primary', type=str, choices=['obb', 'EN_PC', 'KR_PC', 'JP_PC', 'TW_PC', 'CN_PC'])
    parser.add_argument('--obb', type=str, help='Path to obb file. Only valid when --primary is set to obb.')
    parser.add_argument('--patch', type=str, choices=['EN', 'EN_PC', 'KR', 'KR_PC', 'JP', 'JP_PC', 'TW', 'TW_PC', 'CN', 'CN_PC'])
    parser.add_argument('--version', type=str, help='The client version to use. Inferred by default.')
    parser.add_argument('--output', type=str, help='Output directory to use. Required for extraction, not list.')
    parser.add_argument('--decrypt-key', type=str, help='Decryption key to use', default=DECRYPTION_KEY)

    parser.add_argument('--list', action='store_true', help='List all available bundles')

    parser.add_argument('--all-temp', action='store_true', help='Extract all temp (text) bundles')
    parser.add_argument('--all-audio', action='store_true', help='Extract all audio bundles')
    parser.add_argument('--all-video', action='store_true', help='Extract all video bundles')
    parser.add_argument('--all-images', action='store_true', help='Extract all image bundles')
    parser.add_argument('--recode-video', action='store_true', help='Recode h264 in videos')
    parser.add_argument('--nvenc', action='store_true', help='Use NVenc to recode')
    parser.add_argument('--all', action='store_true', help='Extract all i can find')
    parser.add_argument('--cache', type=str, help='Path to sha1 cache file', default='')
    parser.add_argument('--write-settings', action='store_true', help='Write a small settings file to the output directory containing preset and version')
    parser.add_argument('bundles', nargs='*', help='Bundles to extract')
    args = parser.parse_args()

    if args.primary is None:
        args.primary = PRESETS[args.preset]
    if args.patch is None:
        args.patch = PRESETS[args.preset]

    UnityPy.set_assetbundle_decrypt_key(args.decrypt_key)
    ss = SourceSet()
    ss.add_primary(args.primary, args.obb, args.prerelease)
    ss.add_patch(args.patch, args.version)

    if args.list:
        print("Available bundles:")
        for bundle in ss.list_all_bundles():
            print(f" - {bundle}")
        sys.exit(0)

    if not args.output:
        logger.error('Output directory not specified')
        sys.exit(1)

    state = State(ss, args.output, args.decrypt_key, args.recode_video, args.nvenc)
    if any(bundle.endswith('.acb') for bundle in args.bundles) or args.all_audio or args.all:
        state.load_cues()

    # determine all tasks based on flags, use set because we don't want duplicates
    listed_bundles = set(args.bundles)
    listed_bundles.update(bundle for bundle in ss.list_all_bundles() if args.all or
                          (args.all_temp and bundle.endswith('.ab') and 'assets/temp/' in bundle) or
                          (args.all_images and bundle.endswith('.ab') and 'assets/product/texture/' in bundle) or
                          (args.all_audio and bundle.endswith('.acb')) or (args.all_video and bundle.endswith('.usm')))



    if len(listed_bundles) == 0:
        logger.error('No bundles specified')
        sys.exit(1)

    if args.cache:
        listed_bundles = determine_sha1_cache_skip(args.cache, listed_bundles, state)

    non_video_bundles = [bundle for bundle in listed_bundles if not bundle.endswith('.usm')]
    if len(non_video_bundles) > 0:
        logger.info(f"Processing {len(non_video_bundles)} non-video bundles")
        execute_in_pool(non_video_bundles, state, args.cache)

    video_bundles = [bundle for bundle in listed_bundles if bundle.endswith('.usm')]
    if len(video_bundles) > 0:
        logger.info(f"Processing {len(video_bundles)} video bundles")
        execute_in_pool(video_bundles, state, args.cache, max_workers=5, checkpoint_step=1)

    if args.write_settings:
        with open(os.path.join(args.output, 'settings.json'), 'w') as f:
            json.dump({'server': args.preset, 'version': '%d.%d.%d' % ss.version()[:3]}, f)


if __name__ == '__main__':
    main()

