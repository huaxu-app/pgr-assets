import logging
from dataclasses import dataclass
from enum import Enum
from typing import Union, Dict, Tuple

import UnityPy
import msgpack
import requests

from sources import Source


@dataclass
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
    EN = PatchCdnData('http://prod-encdn-volcdn.kurogame.net/prod', 'com.kurogame.punishing.grayraven.en', 'android')
    EN_PC = PatchCdnData('http://prod-encdn-volcdn.kurogame.net/prod', 'com.kurogame.punishing.grayraven.en.pc',
                         'standalone')
    KR = PatchCdnData('http://prod-krcdn-llt.punishing.net/prod', 'com.herogame.punishing.grayraven.kr', 'android')
    # Broken due to inconsistent
    #KR_PC = PatchCdnData('http://prod-krcdn-llt.punishing.net/prod', 'com.herogame.punishing.grayraven.kr.pc', 'standalone')
    # http://prod.zspnsalicdn.yingxiong.com/prod/client/config/com.kurogame.haru.kuro/2.9.0/standalone/config.tab
    CN_PC = PatchCdnData('http://prod.zspnsalicdn.yingxiong.com/prod', 'com.kurogame.haru.kuro', 'standalone')


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
        try:
            return self.index()[bundle][0]
        except KeyError:
            return None

    def bundle_sha1(self, bundle: str) -> Union[str, None]:
        try:
            return self.index()[bundle][1]
        except KeyError:
            return None

    def resources(self):
        if self._resources is not None:
            return self._resources

        resources = {}
        for bundle, (blob, _, _) in self.index().items():
            resources[blob] = self._cdn_url + blob
        self._resources = resources
        return resources

    def index(self) -> Dict[str, Tuple[str, str, int]]:
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

    def bundle_names(self):
        return self.index().keys()

    @staticmethod
    def get_tab(url: str) -> Dict[str, str]:
        resp = requests.get(url)
        if resp.status_code != 200:
            raise Exception(f"Failed to download raw {url} - {resp.status_code}")

        data = {}
        for line in resp.text.splitlines(False):
            if line == '':
                continue
            key, _, value = line.split('\t')
            data[key] = value

        return data

    def __str__(self):
        return f"PatchCdnSource({self._cdn_name})"
