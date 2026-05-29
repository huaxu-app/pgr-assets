import concurrent.futures
import json
import logging
import os
import sys
from typing import List, Optional, Set

import UnityPy
from tqdm import tqdm

from pgr_assets import extractors
from pgr_assets.audio import ACB, CueRegistry
from pgr_assets.sources import SourceError, SourceSet
from pgr_assets.sources.sourceset import BlobNotFoundException

from ..extractors.video_encoders import BaseVideoEncoder, HlsEncoder, WebMp4Encoder
from .helpers import BundleCommandArgs, build_source_set

logger = logging.getLogger("pgr-assets")

AUDIO_KEY = 62855594017927612

# Worker-local handle to the shared State.
_WORKER_STATE: Optional["State"] = None


class ExtractCommand(BundleCommandArgs):
    convert_binary_tables: bool = False  # Allows converting binary tables into CSV files (WARNING: not everything is supported)
    raw_audio: bool = False  # Store extracted audio from ACB/AWB as WAV files instead of converting them to MP3
    hls: bool = (
        False  # Generate HTTP Live Streaming variants for videos on top of mp4's
    )

    cache: str = ""  # Path to sha1 cache file
    write_settings: bool = False  # Write a small settings file to the output directory containing preset and version

    workers: int = 0  # Number of parallel workers for non-video bundles (0 = CPU count)
    fail_on_error: bool = False  # Exit with a non-zero status if any bundle fails

    def configure(self) -> None:
        super().configure()
        self.set_defaults(func=extract_cmd)


class State:
    output_dir: str
    sources: SourceSet
    cues: CueRegistry
    decrypt_key: str
    convert_binary_tables: bool
    encode_mp3: bool
    game_version: tuple[int, int]
    video_encoders: list[BaseVideoEncoder]

    def __init__(self, sources: SourceSet, args: ExtractCommand, decrypt_key: str):
        version = sources.version()
        assert version is not None, "source version could not be determined"
        self.game_version = (version[0], version[1])

        self.sources = sources
        self.cues = CueRegistry(self.game_version)
        self.output_dir = args.output
        self.decrypt_key = decrypt_key
        self.convert_binary_tables = args.convert_binary_tables
        self.encode_mp3 = not args.raw_audio

        self.video_encoders = [WebMp4Encoder()]
        if args.hls:
            self.video_encoders.append(HlsEncoder())

    def load_cues(self):
        self.cues.init(self.sources)


def process_bundle(bundle: str, state: State):
    bundle_data = state.sources.find_bundle(bundle)
    env = UnityPy.load(bundle_data)
    logger.debug(f"Extracting {bundle}")
    extractors.extract_bundle(
        env,
        output_dir=state.output_dir,
        game_version=state.game_version,
        allow_binary_table_convert=state.convert_binary_tables,
    )


def process_audio(bundle: str, state: State):
    cue_sheet = state.cues.get_cue_sheet(bundle)

    awb_data = b""

    if cue_sheet is not None:
        acb_file = cue_sheet.acb
        base_name = cue_sheet.base_name
        acb_data = state.sources.find_bundle(cue_sheet.acb)
        if cue_sheet.awb:
            awb_data = state.sources.find_bundle(cue_sheet.awb)
    else:
        acb_file = bundle
        base_name = bundle.split("/", 2)[2].split(".")[0].lower()
        acb_data = state.sources.find_bundle(bundle)
        try:
            awb_data = state.sources.find_bundle(bundle.replace(".acb", ".awb"))
        except SourceError:
            # AWB is optional (the ACB may carry its waveforms inline) and its
            # absence or an unreachable CDN shouldn't fail the ACB.
            pass

    acb = ACB(acb_data, awb_data)
    logger.debug(f"Extracting {acb_file}")
    acb.extract(
        key=AUDIO_KEY,
        dirname=os.path.join(state.output_dir, "audio", base_name),
        encode=state.encode_mp3,
    )


def process_usm(bundle: str, state: State):
    if len(state.video_encoders) == 0:
        raise RuntimeError("No video encoders specified, cannot encode videos")

    filename = bundle.split("/", 2)[2].split(".")[0].lower()
    data = state.sources.find_bundle(bundle)
    usm = extractors.PGRUSM(data, key=AUDIO_KEY)
    logger.debug(f"Extracting {filename}")
    usm.extract_video(
        os.path.join(state.output_dir, "video", filename), state.video_encoders
    )


def _init_worker(state: State):
    global _WORKER_STATE
    _WORKER_STATE = state
    UnityPy.set_assetbundle_decrypt_key(state.decrypt_key)


def process(bundle: str) -> bool:
    state = _WORKER_STATE
    assert state is not None
    try:
        if bundle.endswith(".ab"):
            process_bundle(bundle, state)
        elif bundle.endswith(".acb"):
            process_audio(bundle, state)
        elif bundle.endswith(".awb"):
            pass  # ignore awb files, they're extracted with the acb
        elif bundle.endswith(".usm"):
            process_usm(bundle, state)
        else:
            raise ValueError(f"Unsupported bundle type: {bundle}")

        return True
    except BlobNotFoundException as e:
        logger.error(f"Could not resolve {bundle}: {e}")
        return False
    except Exception as e:
        logger.exception(f"Failed to process {bundle}", exc_info=e)
        return False


def determine_sha1_cache_skip(file: str, bundles: Set[str], state: State) -> Set[str]:
    if not os.path.exists(file):
        return bundles

    with open(file, "r") as f:
        cached = json.load(f)

    wanted = set()

    for bundle in bundles:
        if bundle in cached:
            if state.sources.bundle_sha1(bundle) == cached[bundle]:
                logger.debug(f"Skipping {bundle} due to cache")
                continue
        wanted.add(bundle)

    return wanted


def write_sha1_cache(file: str, entries: dict):
    with open(file, "w") as f:
        json.dump(entries, f)


def execute_in_pool(
    bundles: List[str],
    state: State,
    cache: str,
    use_processes: bool,
    max_workers: Optional[int] = None,
    checkpoint_step: int = 100,
) -> int:
    fail_count = 0

    cache_entries: dict = {}
    if cache and os.path.exists(cache):
        with open(cache, "r") as f:
            cache_entries = json.load(f)
    since_checkpoint = 0

    if use_processes:
        # Worker processes receive the (already warmed) state once via the
        # initializer, so only the bundle name is sent per task.
        executor = concurrent.futures.ProcessPoolExecutor(
            max_workers=max_workers, initializer=_init_worker, initargs=(state,)
        )
    else:
        # Threads share this process; point the worker handle at our state.
        global _WORKER_STATE
        _WORKER_STATE = state
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)

    with executor:
        future_to_bundle = {
            executor.submit(process, bundle): bundle for bundle in bundles
        }
        for future in tqdm(
            concurrent.futures.as_completed(future_to_bundle),
            total=len(future_to_bundle),
        ):
            bundle = future_to_bundle[future]
            try:
                ok = future.result()
            except Exception as e:
                # The worker itself crashed (e.g. process killed); record and continue.
                logger.exception(f"Worker crashed on {bundle}", exc_info=e)
                ok = False

            if ok:
                if cache:
                    cache_entries[bundle] = state.sources.bundle_sha1(bundle)
                    since_checkpoint += 1
                    if since_checkpoint >= checkpoint_step:
                        write_sha1_cache(cache, cache_entries)
                        since_checkpoint = 0
            else:
                fail_count += 1

    if cache:
        write_sha1_cache(cache, cache_entries)

    return fail_count


def report_results(ok_count: int, fail_count: int):
    if fail_count:
        logger.error(
            f"Extracted {ok_count} bundles, {fail_count} failed (see errors above)"
        )
    else:
        logger.info(f"Extracted {ok_count} bundles, 0 failed")


def extract_cmd(args: ExtractCommand):
    resolved = build_source_set(args)
    ss = resolved.sources

    state = State(ss, args, resolved.decrypt_key)

    if (
        any(bundle.endswith(".acb") for bundle in args.bundles)
        or args.all_audio
        or args.all
    ):
        state.load_cues()

    # determine all tasks based on flags, use set because we don't want duplicates
    listed_bundles = args.selected_bundles(ss)

    if len(listed_bundles) == 0:
        logger.error("No bundles specified")
        sys.exit(1)

    if args.cache:
        listed_bundles = determine_sha1_cache_skip(args.cache, listed_bundles, state)

    # Warm the index and resource maps once so worker processes inherit (fork) or
    # receive once (spawn) the cached lookups instead of re-fetching them per worker.
    ss.warm()

    # Non video jobs spend a lot of time downloading so overcommit to fill the load
    workers = args.workers or ((os.cpu_count() or 1) * 2)

    fail_count = 0
    ok_count = 0

    non_video_bundles = [
        bundle for bundle in listed_bundles if not bundle.endswith(".usm")
    ]
    if len(non_video_bundles) > 0:
        logger.info(f"Processing {len(non_video_bundles)} non-video bundles")
        batch_failed = execute_in_pool(
            non_video_bundles,
            state,
            args.cache,
            use_processes=True,
            max_workers=workers,
        )
        ok_count += len(non_video_bundles) - batch_failed
        fail_count += batch_failed

    video_bundles = [bundle for bundle in listed_bundles if bundle.endswith(".usm")]
    if len(video_bundles) > 0:
        for encoder in state.video_encoders:
            encoder.setup()

        logger.info(f"Processing {len(video_bundles)} video bundles")
        # Video is ffmpeg-subprocess-bound; threads keep the encoder objects in-process.
        batch_failed = execute_in_pool(
            video_bundles,
            state,
            args.cache,
            use_processes=False,
            max_workers=5,
            checkpoint_step=1,
        )
        ok_count += len(video_bundles) - batch_failed
        fail_count += batch_failed

    if args.write_settings:
        version = ss.version()
        assert version is not None
        with open(os.path.join(args.output, "settings.json"), "w") as f:
            json.dump({"server": args.preset, "version": "%d.%d.%d" % version[:3]}, f)

    report_results(ok_count, fail_count)

    if fail_count and args.fail_on_error:
        sys.exit(1)
