import concurrent.futures
import logging
import os
import sys
from typing import List, Optional

from tqdm import tqdm

from pgr_assets.sources import SourceSet
from pgr_assets.sources.sourceset import BlobNotFoundException
from .helpers import build_source_set, BundleCommandArgs

logger = logging.getLogger("pgr-assets")


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
        with open(os.path.join(state.output_dir, bundle), "wb") as f:
            f.write(bundle_data)
        logger.debug(f"Downloaded {bundle}")
        return bundle
    except BlobNotFoundException as e:
        logger.error(f"Could not resolve {bundle}: {e}")
        return None
    except Exception:
        logger.exception(f"Failed to download {bundle}")
        return None


def execute_in_pool(
    bundles: List[str], state: State, max_workers: Optional[int] = None
):
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process, bundle, state) for bundle in bundles]
        for future in tqdm(
            concurrent.futures.as_completed(futures), total=len(futures)
        ):
            try:
                future.result()
            except Exception:
                logger.exception("Worker crashed during download")


class BundlesCommand(BundleCommandArgs):
    def configure(self) -> None:
        super().configure()
        self.set_defaults(func=bundles_cmd)


def bundles_cmd(args: BundlesCommand):
    args.process_args()
    ss = build_source_set(args)

    state = State(ss, args.output)

    # determine all tasks based on flags, use set because we don't want duplicates
    listed_bundles = args.selected_bundles(ss)

    if len(listed_bundles) == 0:
        logger.error("No bundles specified")
        sys.exit(1)

    # Populate the index/resource maps once on the main thread so download threads
    # only read the shared caches instead of racing to rebuild them.
    ss.warm()

    non_video_bundles = [
        bundle for bundle in listed_bundles if not bundle.endswith(".usm")
    ]
    if len(non_video_bundles) > 0:
        logger.info(f"Processing {len(non_video_bundles)} non-video bundles")
        # Matches the session's 32-connection pool for IO concurrency.
        execute_in_pool(non_video_bundles, state, max_workers=32)

    video_bundles = [bundle for bundle in listed_bundles if bundle.endswith(".usm")]
    if len(video_bundles) > 0:
        logger.info(f"Processing {len(video_bundles)} video bundles")
        execute_in_pool(video_bundles, state, max_workers=5)
