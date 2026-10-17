import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from pgr_assets.models.build import BuildTools, build_target
from pgr_assets.models.cache import BuildCache, Marker
from pgr_assets.models.env import ModelEnv
from pgr_assets.models.files import (
    Publisher,
    dump_json,
    sync_target,
)
from pgr_assets.models.format import (
    BUILD_FILE,
    MANIFEST_FILE,
    MODEL_FILE,
    OLD_SUFFIX,
    STAGING_SUFFIX,
    resolve_target_dir,
)
from pgr_assets.models.gltf import build_gltf
from pgr_assets.models.library import CubemapLibrary
from pgr_assets.models.manifest import build_manifest
from pgr_assets.models.model import Model
from pgr_assets.models.registry import ModelEntry
from pgr_assets.models.report import report_model
from pgr_assets.models.scope import Run, Scope
from pgr_assets.models.tables import Tables
from pgr_assets.models.texture import WEBP, TextureEncoding

logger = logging.getLogger("pgr-assets")

COMPRESS_QUALITY = {"off": 0, "low": 5, "high": 11}
COMPRESS_WORKERS = 4


def _write_target(model: Model, publisher: Publisher, entry: ModelEntry) -> None:
    scene = model.scene
    stored = None
    if scene.parts:
        stored = publisher.publish(MODEL_FILE, b"".join(build_gltf(scene).save_to_bytes()))
    publisher.publish(MANIFEST_FILE, dump_json(build_manifest(model, entry.id, stored)))


@dataclass(kw_only=True)
class Export[E: ModelEntry]:
    """
    Resources every target of one run shares.
    """

    tools: BuildTools
    output: str
    quality: int
    force: bool
    pool: ThreadPoolExecutor
    cache: BuildCache
    run: Run[E]

    def build(self, entry: E) -> None:
        env = self.tools.env
        bundle = f"{entry.model_path}.ab"
        if bundle not in env:
            logger.warning(f"{entry.id}: no prefab bundle in catalog")
            return

        directory = resolve_target_dir(self.output, entry.model_path)
        staging, old = directory + STAGING_SUFFIX, directory + OLD_SUFFIX
        _recover(directory, old)
        shutil.rmtree(staging, ignore_errors=True)
        try:
            marker = None if self.force else self.cache.fresh(directory)
            if marker is not None and marker.textures == self.tools.textures.name:
                self._resync_cached(entry, directory, marker)
                return

            with env.pin(bundle):
                logger.info(f"{entry.id}")
                publisher = Publisher(staging, self.quality, self.pool)
                model = build_target(self.tools, self.run, entry, publisher)
                _write_target(model, publisher, entry)
                report_model(model)
                logger.info(
                    f"  resident: {len(env.resident)} bundles,"
                    f" {env.resident_bytes / 1e6:.0f} MB"
                )
                self.cache.write_marker(
                    staging,
                    env.touched,
                    self.quality,
                    model.scene.cubemaps,
                    self.tools.textures.name,
                )
            _swap_in(staging, directory, old)
            logger.info(f"  -> {directory}")
        except Exception:  # one bad target must not end the run
            logger.exception(f"{entry.id}: failed, nothing swapped in")

    def _resync_cached(self, entry: ModelEntry, directory: str, marker: Marker) -> None:
        if marker.quality != self.quality:
            sync_target(directory, self.quality, self.pool)
            self.cache.write_marker(
                directory, marker.bundles, self.quality, marker.cubemaps, marker.textures
            )
        logger.info(f"{entry.id}: cached")


def _recover(directory: str, old: str) -> None:
    """
    Put back the build a crash left parked under OLD_SUFFIX.
    """
    if os.path.isdir(old):
        if os.path.isdir(directory):
            shutil.rmtree(old, ignore_errors=True)
        else:
            os.replace(old, directory)
            logger.warning(f"{directory}: restored from an interrupted swap")


def _swap_in(staging: str, directory: str, old: str) -> None:
    """
    Replace the directory with the staged build. The marker is already in staging.
    """
    if os.path.isdir(directory):
        os.replace(directory, old)
    os.replace(staging, directory)
    shutil.rmtree(old, ignore_errors=True)


def _read_markers(output: str) -> list[Marker]:
    """
    Every built target under the output, this run's or an earlier one's.
    """
    found: list[Marker] = []
    for directory, names, files in os.walk(output):
        if BUILD_FILE in files:
            try:
                found.append(Marker.read(directory))
            except (OSError, ValueError, KeyError) as error:
                logger.warning(f"{directory}: build marker unreadable, {error!r}")
            names[:] = []
        else:
            names[:] = [n for n in names if not n.endswith((STAGING_SUFFIX, OLD_SUFFIX))]
    return found


def _prune_cubemaps(output: str, cubemaps: CubemapLibrary) -> None:
    """
    The library covers the whole tree, so it keeps what every marker on disk names,
    not just this run's selection.
    """
    cubemaps.prune({name for m in _read_markers(output) for name in m.cubemaps})


def export_models[E: ModelEntry](
    env: ModelEnv,
    tables: Tables,
    entries: list[E],
    output: str,
    scope: Scope[E],
    *,
    force: bool = False,
    compress: str = "off",
    textures: TextureEncoding = WEBP,
) -> None:
    """
    Export a selection using one shared cubemap collection and compression pool.
    """
    quality = COMPRESS_QUALITY[compress]
    with ThreadPoolExecutor(COMPRESS_WORKERS, thread_name_prefix="brotli") as pool:
        run = scope.start(tables)
        tables.forget()
        cubemaps = CubemapLibrary(output, quality, force)
        export = Export(
            tools=BuildTools(env, tables, cubemaps, textures),
            output=output,
            quality=quality,
            force=force,
            pool=pool,
            # Every table read so far feeds every target, so it is part of each key.
            cache=BuildCache(env.sources, env.touched),
            run=run,
        )
        for entry in entries:
            export.build(entry)
            cubemaps.write()
        _prune_cubemaps(output, cubemaps)
