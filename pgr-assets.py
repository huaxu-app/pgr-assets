import dataclasses
import os
import argparse
import logging
import sys
from enum import Enum
from typing import Dict, Tuple, Union, List
from zipfile import ZipFile

import UnityPy
import msgpack
import requests

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('pgr-assets')

DECRYPTION_KEY = 'y5XPvqLOrCokWRIa'


class Source(object):
    def has_blob(self, path: str) -> bool:
        """Returns true if the source has the blob at the given path"""
        raise NotImplementedError()

    def get_blob(self, path: str) -> bytes:
        """Returns the blob at the given path as binary data"""
        raise NotImplementedError()

    def bundle_to_blob(self, bundle: str) -> Union[str, None]:
        """Returns the blob that contains the bundle, or None if unknown"""
        raise NotImplementedError()

    def version(self) -> Union[str, None]:
        """Returns the version of the source, or None if unknown"""
        raise NotImplementedError()


@dataclasses.dataclass
class PcStarterData:
    cdn: str
    game_id: int
    iteration: int

    def index_url(self):
        return f'{self.cdn}pcstarter/prod/game/G{self.game_id}/{self.iteration}/index.json'


class PcStarterCdn(Enum):
    EN_PC = PcStarterData('https://prod-awscdn-gamestarter.kurogame.net/', 143, 4)


class PcStarterSource(Source):
    _logger = logging.getLogger('PcStarterSource')
    _index = None
    _resources = None

    def __init__(self, cdn: PcStarterCdn):
        self._cdn_name = cdn.name
        self._cdn = cdn.value

    def index(self):
        if self._index is not None:
            return self._index

        self._logger.debug("Getting index from launcher cdn")
        self._index = self._get_json(self._cdn.index_url())
        return self._index

    def has_blob(self, blob: str) -> bool:
        return blob in self.resources()

    def get_blob(self, blob: str) -> bytes:
        url = self.resources()[blob]
        self._logger.debug(f"Downloading blob {blob} ({url})")
        resp = requests.get(url)
        if resp.status_code != 200:
            raise Exception(f"Failed to download blob {blob} - {resp.status_code}")
        return resp.content

    def version(self) -> Union[str, None]:
        return self.index()['default']['version']

    def base_path(self):
        return self.index()['default']['resourcesBasePath']

    def bundle_to_blob(self, bundle: str) -> Union[str, None]:
        return None

    def resources(self):
        if self._resources is not None:
            return self._resources

        resource_index = self._get_json(self._cdn.cdn + self.index()['default']['resources'])
        resources = {}
        for resource in resource_index['resource']:
            blob = resource['dest'].split('/')[-1]
            resources[blob] = self._cdn.cdn + self.base_path() + resource['dest']
        self._resources = resources
        return resources

    @staticmethod
    def _get_json(url: str) -> dict:
        resp = requests.get(url)
        if resp.status_code != 200:
            raise Exception(f"Failed to download json {url} - {resp.status_code}")
        return resp.json()

    def __str__(self):
        return f"PcStarterSource({self._cdn_name})"


@dataclasses.dataclass
class PatchCdnData:
    """
    Settings required to use a patch CDN for a server
    """
    cdn: str
    app_id: str
    platform: str

    def config_url(self, version: str):
        return f'{self.cdn}/client/config/{self.app_id}/{version}/{self.platform}/config.tab'

    def base_url(self, application_version: str, document_version: str):
        return '/'.join([
            self.cdn, 'client/patch', self.app_id, application_version, self.platform, document_version, 'matrix/'
        ])


# CDN base url, app_id, platform From the config tab PrimaryCdn
# http://prod-encdn-akamai.kurogame.net/prod/client/config/com.kurogame.punishing.grayraven.en.pc/1.28.0/standalone/config.tab
class PatchCdn(Enum):
    EN_PC = PatchCdnData('http://prod-encdn-akamai.kurogame.net/prod', 'com.kurogame.punishing.grayraven.en.pc',
                         'standalone')
    KR = PatchCdnData('http://prod-krcdn-akamai.punishing.net/prod', 'com.herogame.punishing.grayraven.kr', 'android')


class PatchCdnSource(Source):
    _logger = logging.getLogger('PatchCdnSource')
    _index = None
    _resources = None

    def __init__(self, cdn: PatchCdn, version: str):
        self._cdn_name = cdn.name
        self._cdn = cdn.value

        self._logger.debug("Getting config from patch cdn")
        config = self.get_tab(self._cdn.config_url(version))
        application_version = config["ApplicationVersion"]
        document_version = config["DocumentVersion"]
        self._cdn_url = self._cdn.base_url(application_version, document_version)
        self._logger.debug(f"Using patch cdn {self._cdn_url}")
        self._version = application_version

    def has_blob(self, blob: str) -> bool:
        return blob in self.resources()

    def get_blob(self, blob: str) -> bytes:
        url = self.resources()[blob]
        self._logger.debug(f"Downloading blob {blob} ({url})")
        resp = requests.get(url)
        if resp.status_code != 200:
            raise Exception(f"Failed to download blob {blob} - {resp.status_code}")
        return resp.content

    def bundle_to_blob(self, bundle: str) -> Union[str, None]:
        return self.index()[bundle][0]

    def resources(self):
        if self._resources is not None:
            return self._resources

        resources = {}
        for bundle, (blob, _, _) in self.index().items():
            resources[blob] = self._cdn_url + blob
        self._resources = resources
        return resources

    def index(self):
        if self._index is not None:
            return self._index

        # Index is an asset bundle, containing the msgpack'd index
        bundle = requests.get(f'{self._cdn_url}index')
        if bundle.status_code != 200:
            raise Exception(f"Failed to download patch index - {bundle.status_code}")
        env = UnityPy.load(bundle.content)

        if 'assets/temp/index.bytes' not in env.container:
            raise Exception(f"Failed to find index in patch index bundle")

        self._index = msgpack.loads(env.container['assets/temp/index.bytes'].read().script)[0]
        return self._index

    def version(self) -> Union[str, None]:
        return self._version

    @staticmethod
    def get_tab(url: str) -> Dict[str, str]:
        resp = requests.get(url)
        if resp.status_code != 200:
            raise Exception(f"Failed to download raw {url} - {resp.status_code}")

        data = {}
        for line in resp.text.splitlines(False):
            key, _, value = line.split('\t')
            data[key] = value

        return data

    def __str__(self):
        return f"PatchCdnSource({self._cdn_name})"


class ObbSource(Source):
    _resources = None

    def __init__(self, obb: str):
        self._obb = ZipFile(obb, 'r')

    def has_blob(self, blob: str) -> bool:
        return blob in self.resources()

    def get_blob(self, blob: str) -> bytes:
        return self._obb.read(self.resources()[blob])

    def bundle_to_blob(self, bundle: str) -> Union[str, None]:
        # This can't resolve bundles to blobs
        return None

    def version(self) -> Union[str, None]:
        return None

    def resources(self) -> Dict[str, str]:
        if self._resources is not None:
            return self._resources

        self._resources = {f.filename.split('/')[-1]: f.filename for f in self._obb.filelist if 'matrix' in f.filename}
        return self._resources

    def __str__(self):
        return f"ObbSource({self._obb.filename})"


def rewrite_text_asset(path: str, data: memoryview) -> Tuple[str, bytearray]:
    # RSA signature can fuck itself
    data = bytearray(data[128:])

    # Almost all files end with .bytes
    # If it doesn't, we'll keep it as it is,
    # otherwise we drop the '.bytes' extension
    path_without_bytes, ext = os.path.splitext(path)
    if ext != ".bytes":
        return path, data

    path = path_without_bytes
    ext = os.path.splitext(path)[1]

    if ext == ".lua":
        logger.warning('Extracting lua files is unsupported atm')

    return path, data


def extract_bundle(env: UnityPy.Environment, output_dir: str):
    for path, obj in env.container.items():
        dest = os.path.join(output_dir, *path.split("/"))
        # create dest based on original path
        # make sure that the dir of that path exists
        os.makedirs(os.path.dirname(dest), exist_ok=True)

        try:
            if obj.type.name in ["Texture2D", "Sprite"]:
                data = obj.read()
                # correct extension
                dest, ext = os.path.splitext(dest)
                dest = dest + ".png"
                data.image.save(dest)
                logger.debug(f"Extracted {path}")
            elif obj.type.name == "TextAsset":
                data = obj.read()
                dest, data = rewrite_text_asset(dest, data.script)
                with open(dest, "wb") as f:
                    f.write(data)
                logger.debug(f"Extracted {path}")
            else:
                logger.warning(f"Unsupported type {obj.type.name} for {path}")
        except Exception as e:
            logger.error(f"Failed to extract {path}: {e}")


def find_bundle(bundle: str, sources: List[Source]) -> bytes:
    # First we try to resolve bundle -> blob
    for source in sources:
        blob = source.bundle_to_blob(bundle)
        if blob is not None:
            break
    else:
        raise Exception(f"Failed to resolve bundle {bundle}")

    logger.debug(f"Bundle {bundle} -> blob {blob}")

    # Then find the first source that has the blob
    for source in sources:
        if source.has_blob(blob):
            logger.info(f"Downloading blob {blob} from {source}")
            return source.get_blob(blob)
    raise Exception(f"Failed to resolve blob {blob}")


def get_primary(version: str, primary_type: str, obb: Union[str, None]) -> Source:
    impl = None

    if primary_type == 'obb':
        impl = ObbSource(obb)
    elif primary_type in PcStarterCdn.__members__:
        impl = PcStarterSource(PcStarterCdn[primary_type])

    if impl is None:
        raise Exception(f"Unknown primary type {primary_type}")

    impl_version = impl.version()
    logger.info(f"Primary source {impl} version {impl_version}")
    if impl_version is not None and version != impl_version:
        logger.error(f"Primary source version mismatch. Expected {version}, got {impl_version}")
        sys.exit(1)

    return impl


def get_patch(version: str, patch_type: str) -> Source:
    if patch_type not in PatchCdn.__members__:
        raise Exception(f"Unknown patch type {patch_type}")

    impl = PatchCdnSource(PatchCdn[patch_type], version)

    impl_version = impl.version()
    logger.info(f"Patch source {patch_type} version {impl_version}")
    if impl_version is not None and version != impl_version:
        logger.error(f"Patch source version mismatch. Expected {version}, got {impl_version}")
        sys.exit(1)

    return impl


def main():
    parser = argparse.ArgumentParser(description='Extracts the assets required for kennel')
    parser.add_argument('--primary', type=str, choices=['obb', 'EN_PC'], default='EN_PC')
    parser.add_argument('--obb', type=str, help='Path to obb file. Only valid when --primary is set to obb.')

    parser.add_argument('--patch', type=str, choices=['EN_PC', 'KR'], default='EN_PC')

    parser.add_argument('--version', type=str, help='The client version to use.', required=True)
    parser.add_argument('--output', type=str, help='Output directory to use', required=True)
    parser.add_argument('bundles', nargs='*', help='Bundles to extract')
    args = parser.parse_args()

    if len(args.bundles) == 0:
        parser.error('No bundles specified')

    UnityPy.set_assetbundle_decrypt_key(DECRYPTION_KEY)

    primary_source = get_primary(args.version, args.primary, args.obb)
    patch_source = get_patch(args.version, args.patch)

    for bundle in args.bundles:
        bundle_data = find_bundle(bundle, [primary_source, patch_source])
        env = UnityPy.load(bundle_data)
        logger.info(f"Extracting {bundle}")
        extract_bundle(env, output_dir=args.output)


if __name__ == '__main__':
    main()
