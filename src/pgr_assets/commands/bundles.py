import concurrent.futures
import logging
import os
import sys
from typing import List

from tqdm import tqdm

from pgr_assets.sources import SourceSet
from .helpers import build_source_set, BaseArgs

logger = logging.getLogger('pgr-assets')

AUDIO_KEY = 62855594017927612


class State:
    output_dir: str
    sources: SourceSet

    def __init__(self, sources: SourceSet, output_dir: str):
        self.sources = sources
        self.output_dir = output_dir


def process(bundle: str, state: State):
    try:
        bundle_data = state.sources.find_bundle(bundle)
        out_path = os.path.join(state.output_dir, bundle)
        if not os.path.exists(os.path.dirname(out_path)):
            os.makedirs(os.path.dirname(out_path))
        with open(os.path.join(state.output_dir, bundle), 'wb') as f:
            f.write(bundle_data)
        logger.debug(f"Downloaded {bundle}")
    except Exception as e:
        logger.exception(f"Failed to download {bundle}", exc_info=e)
        return None


def execute_in_pool(bundles: List[str], state: State, max_workers: int = None):
    finished_bundles = list()

    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process, bundle, state) for bundle in bundles]
        for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures)):
            try:
                result = future.result()
                if result:
                    finished_bundles.append(result)
            except Exception as e:
                logger.error(f"Failed to process bundle: {e}")


class BundlesCommand(BaseArgs):
    output: str  # Output directory to use.
    all_temp: bool = False  # Extract all temp (text) bundles
    all_audio: bool = False  # Extract all audio bundles
    all_video: bool = False  # Extract all video bundles
    all_images: bool = False  # Extract all image bundles

    all: bool = False  # Extract all I can find
    bundles: List[str]  # Bundles to extract

    def configure(self) -> None:
        self.add_argument('bundles', nargs='*', help='Bundles to extract')
        self.set_defaults(func=bundles_cmd)


def bundles_cmd(args: BundlesCommand):
    args.process_args()
    ss = build_source_set(args)

    state = State(ss, args.output)

    # determine all tasks based on flags, use set because we don't want duplicates
    listed_bundles = set(args.bundles)
    listed_bundles.update(bundle for bundle in ss.list_all_bundles() if args.all or
                          (args.all_temp and bundle.endswith('.ab') and 'assets/temp/' in bundle) or
                          (args.all_images and bundle.endswith('.ab') and 'assets/product/texture/' in bundle) or
                          (args.all_audio and bundle.endswith('.acb')) or (args.all_video and bundle.endswith('.usm')))

    if len(listed_bundles) == 0:
        logger.error('No bundles specified')
        sys.exit(1)

    non_video_bundles = [bundle for bundle in listed_bundles if not bundle.endswith('.usm')]
    if len(non_video_bundles) > 0:
        logger.info(f"Processing {len(non_video_bundles)} non-video bundles")
        execute_in_pool(non_video_bundles, state)

    video_bundles = [bundle for bundle in listed_bundles if bundle.endswith('.usm')]
    if len(video_bundles) > 0:
        logger.info(f"Processing {len(video_bundles)} video bundles")
        execute_in_pool(video_bundles, state, max_workers=5)
