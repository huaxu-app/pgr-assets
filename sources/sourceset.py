import logging
from typing import Union

from sources import PatchCdn, PatchCdnSource, ObbSource, PcStarterSource, PcStarterCdn, Source

logger = logging.getLogger('sourceset')


class SourceSet:
    def __init__(self):
        self.sources = []

    def add_primary(self, version: str, primary_type: str, obb: Union[str, None]):
        if primary_type == 'obb':
            impl = ObbSource(obb)
        elif primary_type in PcStarterCdn.__members__:
            impl = PcStarterSource(PcStarterCdn[primary_type])
        else:
            raise Exception(f"Unknown primary type {primary_type}")

        impl_version = impl.version()
        logger.info(f"Primary source {impl} version {impl_version}")
        # if impl_version is not None and version != impl_version:
        #     logger.error(f"Primary source version mismatch. Expected {version}, got {impl_version}")
        #     sys.exit(1)

        self.sources.append(impl)

    def add_patch(self, patch_type: str, version: str):
        if patch_type not in PatchCdn.__members__:
            raise Exception(f"Unknown patch type {patch_type}")

        impl = PatchCdnSource(PatchCdn[patch_type], version)

        impl_version = impl.version()
        logger.info(f"Patch source {patch_type} version {impl_version}")
        # if impl_version is not None and version != impl_version:
        #    logger.error(f"Patch source version mismatch. Expected {version}, got {impl_version}")
        #    sys.exit(1)

        self.sources.append(impl)

    def list_all_bundles(self):
        return set(bundle for source in self.sources for bundle in source.bundle_names())

    def find_bundle(self, bundle):
        # First we try to resolve bundle -> blob, but use the last source that has it
        for source in reversed(self.sources):
            blob = source.bundle_to_blob(bundle)
            if blob is not None:
                break
        else:
            raise Exception(f"Failed to resolve bundle {bundle}")

        logger.debug(f"Bundle {bundle} -> blob {blob}")

        # Then find the first source that has the blob
        for source in self.sources:
            if source.has_blob(blob):
                logger.info(f"Downloading blob {blob} from {source}")
                try:
                    return source.get_blob(blob)
                except Exception as e:
                    logger.error(f"Failed to get blob {blob} from {source}: {e}")

        raise Exception(f"Failed to resolve blob {blob}")