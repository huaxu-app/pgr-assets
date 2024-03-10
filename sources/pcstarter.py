import logging
from typing import Union

import requests

from sources import Source
from dataclasses import dataclass
from enum import Enum


@dataclass
class PcStarterData:
    cdn: str
    game_id: int
    iteration: int

    def index_url(self):
        return f'{self.cdn}pcstarter/prod/game/G{self.game_id}/{self.iteration}/index.json'


class PcStarterCdn(Enum):
    EN_PC = PcStarterData('https://prod-alicdn-gamestarter.kurogame.com/', 143, 4)
    CN_PC = PcStarterData('https://prod-cn-alicdn-gamestarter.kurogame.com/', 148, 10001)


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

    def blob_cdn_url(self):
        return self.index()['default']['cdnList'][0]['url']

    def bundle_to_blob(self, bundle: str) -> Union[str, None]:
        return None

    def resources(self):
        if self._resources is not None:
            return self._resources

        blob_base = self.blob_cdn_url()

        resource_index = self._get_json(blob_base + self.index()['default']['resources'])
        resources = {}
        for resource in resource_index['resource']:
            blob = resource['dest'].split('/')[-1]
            resources[blob] = blob_base + self.base_path() + resource['dest']
        self._resources = resources
        return resources

    def bundle_names(self):
        return self.index().keys()

    @staticmethod
    def _get_json(url: str) -> dict:
        resp = requests.get(url)
        if resp.status_code != 200:
            raise Exception(f"Failed to download json {url} - {resp.status_code}")
        return resp.json()

    def __str__(self):
        return f"PcStarterSource({self._cdn_name})"