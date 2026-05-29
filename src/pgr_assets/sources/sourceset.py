import logging
from typing import Union, Tuple

from pgr_assets.versions import PATCH_KEY_SCHEME_MIN_VERSION, parse_version

from . import PatchCdn, PatchCdnSource, ObbSource, PcStarterSource, PcStarterCdn, Source
from .exceptions import BlobNotFoundException, SourceError, UnknownSourceError
from .xbuildconfig import extract_build_key

logger = logging.getLogger("sourceset")

# Re-exported for callers that import it from this module historically.
__all__ = ["SourceSet", "BlobNotFoundException"]


class SourceSet:
    def __init__(self):
        self.sources: list[Source] = []

    def add_primary(self, primary_type: str, obb: Union[str, None], prerelease: bool):
        if primary_type == "obb":
            assert obb is not None, "obb path required when primary is 'obb'"
            impl = ObbSource(obb)
        elif primary_type in PcStarterCdn.__members__:
            impl = PcStarterSource(PcStarterCdn[primary_type], prerelease)
        else:
            raise UnknownSourceError(f"Unknown primary type {primary_type}")

        impl_version = impl.version()
        logger.info(f"Primary source {impl} version {impl_version}")

        self.sources.append(impl)

    def add_patch(self, patch_type: str, version: Union[str, None]):
        if patch_type not in PatchCdn.__members__:
            raise UnknownSourceError(f"Unknown patch type {patch_type}")

        if version is None:
            inferred = self.version()
            if inferred is not None:
                version_nibbles = inferred[:3]
                # Patch never has .patch versions even if pc has them
                if len(version_nibbles) == 3 and version_nibbles[-1] != 0:
                    version_nibbles = (version_nibbles[0], version_nibbles[1], 0)
                version = "%d.%d.%d" % version_nibbles
        if version is None:
            raise SourceError(
                "Patch version required, and could not be inferred from earlier sources"
            )

        key = None
        if parse_version(version) >= PATCH_KEY_SCHEME_MIN_VERSION:
            key = extract_build_key(self._resources_assets_bytes())
            logger.debug("Extracted patch key from resources.assets")

        impl = PatchCdnSource(PatchCdn[patch_type], version, key=key)

        impl_version = impl.version()
        logger.info(f"Patch source {patch_type} version {impl_version}")
        # if impl_version is not None and version != impl_version:
        #    logger.error(f"Patch source version mismatch. Expected {version}, got {impl_version}")
        #    sys.exit(1)

        self.sources.append(impl)

    def version(self) -> Union[Tuple[int, ...], None]:
        for source in self.sources:
            version = source.version()
            if version is not None:
                return version
        return None

    def _resources_assets_bytes(self) -> bytes:
        for source in self.sources:
            if source.has_blob("resources.assets"):
                return source.get_blob("resources.assets")
        raise BlobNotFoundException(
            "resources.assets not found in any source (required for >=4.3.0 patch key)"
        )

    def list_all_bundles(self):
        return set(
            bundle for source in self.sources for bundle in source.bundle_names()
        )

    def warm(self):
        for source in self.sources:
            source.bundle_names()
            source.resources()

    def bundle_to_blob(self, bundle):
        for source in reversed(self.sources):
            blob = source.bundle_to_blob(bundle)
            if blob is not None:
                return blob
        return None

    def bundle_sha1(self, bundle):
        for source in reversed(self.sources):
            sha1 = source.bundle_sha1(bundle)
            if sha1 is not None:
                return sha1
        return None

    def find_bundle(self, bundle):
        blob = self.bundle_to_blob(bundle)
        # First we try to resolve bundle -> blob, but use the last source that has it
        if blob is None:
            raise BlobNotFoundException(f"Failed to resolve bundle {bundle}")

        logger.debug(f"Bundle {bundle} -> blob {blob}")

        # Then find the first source that has the blob
        for source in self.sources:
            if source.has_blob(blob):
                logger.debug(f"Downloading blob {blob} from {source}")
                try:
                    return source.get_blob(blob)
                except Exception as e:
                    logger.error(f"Failed to get blob {blob} from {source}: {e}")

        raise BlobNotFoundException(f"Failed to resolve blob {blob}")
