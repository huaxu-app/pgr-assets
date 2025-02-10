import logging
from typing import Union, Tuple

from sources import PatchCdn, PatchCdnSource, ObbSource, PcStarterSource, PcStarterCdn

logger = logging.getLogger('sourceset')


class SourceSet:
    def __init__(self):
        self.sources = []

    def add_primary(self, primary_type: str, obb: Union[str, None], prerelease: bool):
        if primary_type == 'obb':
            impl = ObbSource(obb)
        elif primary_type in PcStarterCdn.__members__:
            impl = PcStarterSource(PcStarterCdn[primary_type], prerelease)
        else:
            raise Exception(f"Unknown primary type {primary_type}")

        impl_version = impl.version()
        logger.info(f"Primary source {impl} version {impl_version}")

        self.sources.append(impl)

    def add_patch(self, patch_type: str, version: Union[str, None]):
        if patch_type not in PatchCdn.__members__:
            raise Exception(f"Unknown patch type {patch_type}")

        if version is None:
            version = '%d.%d.%d' % self.version()[:3]
        if version is None:
            raise Exception("Patch version required, and could not be inferred from earlier sources")

        impl = PatchCdnSource(PatchCdn[patch_type], version)

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

    def disable_primary(self):
        self.sources = [source for source in self.sources if isinstance(source, PatchCdnSource)]

    def list_all_bundles(self):
        return set(bundle for source in self.sources for bundle in source.bundle_names())

    def bundle_to_blob(self, bundle):
        for source in self.sources:
            blob = source.bundle_to_blob(bundle)
            if blob is not None:
                return blob
        return None

    def bundle_sha1(self, bundle):
        for source in self.sources:
            sha1 = source.bundle_sha1(bundle)
            if sha1 is not None:
                return sha1
        return None

    def find_bundle(self, bundle):
        blob = self.bundle_to_blob(bundle)
        # First we try to resolve bundle -> blob, but use the last source that has it
        if blob is None:
            raise Exception(f"Failed to resolve bundle {bundle}")

        logger.debug(f"Bundle {bundle} -> blob {blob}")

        # Then find the first source that has the blob
        for source in self.sources:
            if source.has_blob(blob):
                logger.debug(f"Downloading blob {blob} from {source}")
                try:
                    return source.get_blob(blob)
                except Exception as e:
                    logger.error(f"Failed to get blob {blob} from {source}: {e}")

        raise Exception(f"Failed to resolve blob {blob}")
