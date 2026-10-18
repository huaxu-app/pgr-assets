import concurrent.futures
import json
import logging
import os
import sys
from multiprocessing.queues import Queue
from typing import Optional

import UnityPy
from tqdm import tqdm

from pgr_assets import extractors
from pgr_assets.audio import ACB, CueRegistry
from pgr_assets.audio.paths import AUDIO_DIR, sheet_base_name
from pgr_assets.audio.render import MP3, WAV, AudioFormat
from pgr_assets.audio.variants import (
    collect_variants,
    write_aggregate,
    write_bank_variants,
)
from pgr_assets.image_names import find_ambiguous_images, make_image_reference
from pgr_assets.logging_setup import log_to_queue, worker_logs
from pgr_assets.sources import SourceError, SourceSet
from pgr_assets.sources.sourceset import BlobNotFoundException

from ..extractors.video_encoders import BaseVideoEncoder, HlsEncoder, WebMp4Encoder
from .helpers import BundleCommandArgs, build_source_set, selected_bundles

logger = logging.getLogger("pgr-assets")

AUDIO_KEY = 62855594017927612

# Worker-local handle to the shared State.
_WORKER_STATE: Optional["State"] = None


class ExtractCommand(BundleCommandArgs):
    convert_binary_tables: bool = False  # Convert supported binary tables to CSV
    raw_audio: bool = False  # Write WAV audio instead of MP3
    hls: bool = False  # Write HLS variants alongside MP4 videos
    no_webp: bool = False  # Skip WebP images and thumbnails, write PNG only

    cache: str | None = None  # Path to sha1 cache file
    write_settings: bool = (
        False  # Write preset, version and asset metadata to settings.json
    )

    workers: int = 0  # Non-video workers (0 = twice CPU count)
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
    webp: bool
    audio_format: AudioFormat
    game_version: tuple[int, int]
    video_encoders: list[BaseVideoEncoder]
    ambiguous_images: dict[str, str]

    def __init__(self, sources: SourceSet, args: ExtractCommand, decrypt_key: str):
        version = sources.version()
        assert version is not None, "source version could not be determined"
        self.game_version = (version[0], version[1])

        self.sources = sources
        self.cues = CueRegistry(self.game_version)
        self.output_dir = args.output
        self.decrypt_key = decrypt_key
        self.convert_binary_tables = args.convert_binary_tables
        self.webp = not args.no_webp
        self.audio_format = WAV if args.raw_audio else MP3
        self.ambiguous_images = {}

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
        ambiguous_images=state.ambiguous_images,
        webp=state.webp,
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
        base_name = sheet_base_name(bundle)
        acb_data = state.sources.find_bundle(bundle)
        try:
            awb_data = state.sources.find_bundle(bundle.replace(".acb", ".awb"))
        except SourceError:
            # AWB is optional (the ACB may carry its waveforms inline) and its
            # absence or an unreachable CDN shouldn't fail the ACB.
            pass

    acb = ACB(acb_data, awb_data)
    logger.debug(f"Extracting {acb_file}")
    dirname = os.path.join(state.output_dir, AUDIO_DIR, base_name)
    variants = acb.extract(AUDIO_KEY, dirname, state.audio_format)
    write_bank_variants(dirname, variants)


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


def _init_worker(state: State, queue: Queue, level: int):
    log_to_queue(queue, level)
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


def determine_sha1_cache_skip(file: str, bundles: set[str], state: State) -> set[str]:
    if not os.path.exists(file):
        return bundles

    with open(file, "r") as f:
        cached = json.load(f)

    wanted = set()

    for bundle in bundles:
        if bundle in cached and state.sources.bundle_sha1(bundle) == cached[bundle]:
            logger.debug(f"Skipping {bundle} due to cache")
            continue
        wanted.add(bundle)

    return wanted


def write_sha1_cache(file: str, entries: dict):
    with open(file, "w") as f:
        json.dump(entries, f)


def execute_in_pool(
    bundles: list[str],
    state: State,
    cache: str | None,
    use_processes: bool,
    max_workers: int | None = None,
    checkpoint_step: int = 100,
) -> int:
    fail_count = 0

    cache_entries: dict = {}
    if cache and os.path.exists(cache):
        with open(cache, "r") as f:
            cache_entries = json.load(f)
    since_checkpoint = 0

    with worker_logs() as (queue, level):
        if use_processes:
            # Worker processes receive the (already warmed) state once via the
            # initializer, so only the bundle name is sent per task.
            executor = concurrent.futures.ProcessPoolExecutor(
                max_workers=max_workers,
                initializer=_init_worker,
                initargs=(state, queue, level),
            )
        else:
            # Threads use this process's shared worker state.
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
                    # Record worker crashes as failed bundles.
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

    # Derive collisions from every bundle the source knows about
    state.ambiguous_images = find_ambiguous_images(ss.list_all_bundles())

    listed_bundles = selected_bundles(args, ss)

    if len(listed_bundles) == 0:
        logger.error("No bundles specified")
        sys.exit(1)

    has_audio = any(bundle.endswith(".acb") for bundle in listed_bundles)
    if has_audio:
        state.load_cues()

    if args.cache:
        listed_bundles = determine_sha1_cache_skip(args.cache, listed_bundles, state)

    # Populate source caches before copying state to worker processes.
    ss.warm()

    # Downloads leave workers idle, so default to twice the CPU count.
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
        # ffmpeg runs in subprocesses, so threads can share the encoder objects.
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

    # Rebuild from bank sidecars even when the sha1 cache skips every bank.
    audio_dir = os.path.join(args.output, AUDIO_DIR)
    variants = {}
    if has_audio:
        variants = write_aggregate(audio_dir)
    elif args.write_settings:
        variants = collect_variants(audio_dir)

    if args.write_settings:
        version = ss.version()
        assert version is not None
        with open(os.path.join(args.output, "settings.json"), "w") as f:
            json.dump(
                {
                    "server": args.preset,
                    "version": "{}.{}.{}".format(*version[:3]),
                    "ambiguous_images": sorted(
                        make_image_reference(stem) for stem in state.ambiguous_images
                    ),
                    "audio_variants": {
                        f"{AUDIO_DIR}/{sheet}/{cue}": suffixes
                        for sheet, cues in sorted(variants.items())
                        for cue, suffixes in sorted(cues.items())
                    },
                },
                f,
            )

    report_results(ok_count, fail_count)

    if fail_count and args.fail_on_error:
        sys.exit(1)
