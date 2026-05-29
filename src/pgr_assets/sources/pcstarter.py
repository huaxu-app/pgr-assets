import logging
from typing import Union, Tuple

import UnityPy

from pgr_assets.versions import parse_version

from . import Source
from ._index import read_textasset_bytes, loads_index
from .exceptions import BlobDownloadError, SourceIndexError
from .session import get_session
from dataclasses import dataclass
from enum import Enum


@dataclass
class PcStarterData:
    cdn: str
    game_id: int
    iteration: int | str
    predownload: bool

    def index_url(self):
        return f"{self.cdn}game/G{self.game_id}/{self.iteration}/index.json"


class PcStarterCdn(Enum):
    # EN_PC = PcStarterData('https://prod-alicdn-gamestarter.kurogame.com/', 143, 4, False)
    EN_PC = PcStarterData(
        "https://prod-alicdn-gamestarter.kurogame.com/launcher/",
        143,
        "50015_LWdk9D2Ep9mpJmqBZZkcPBU2YNraEWBQ",
        False,
    )
    KR_PC = PcStarterData(
        "https://prod-alicdn-gamestarter.kurogame.com/launcher/",
        286,
        "50011_XefwDdpgPxxLABoTOD0yuqTFBC3koJZ0",
        False,
    )
    JP_PC = PcStarterData(
        "https://prod-alicdn-gamestarter.kurogame.com/launcher/",
        282,
        "50007_NxWGZ0d254oWqZKuuL6szOK7WRLPt668",
        False,
    )
    TW_PC = PcStarterData(
        "https://prod-alicdn-gamestarter.kurogame.com/launcher/",
        279,
        "50016_i2n5NLmdCAmOGP3J1tJOlWKNSMQuyWL7",
        False,
    )
    CN_PC = PcStarterData(
        "https://prod-cn-alicdn-gamestarter.kurogame.com/launcher/",
        148,
        "10011_qYQv6TyyyhCKD3ox3gssyolNPwMoCPZt",
        False,
    )
    CN_PC_BETA = PcStarterData(
        "https://prod-cn-alicdn-gamestarter.kurogame.com/launcher/",
        148,
        "10013_Gp9Gz1u9I5eyllXu64TfWhaPBQFXB449",
        False,
    )


class PcStarterSource(Source):
    _logger = logging.getLogger("PcStarterSource")
    _cdn_index: dict | None = None
    _matrix_index: dict | None = None
    _resources: dict | None = None
    _section: str

    def __init__(self, cdn: PcStarterCdn, prerelease: bool):
        self._cdn_name = cdn.name
        self._cdn = cdn.value
        self._section = "predownload" if prerelease else "default"

    def cdn_index(self):
        if self._cdn_index is not None:
            return self._cdn_index

        self._logger.debug("Getting index from launcher cdn")
        self._cdn_index = self._get_json(self._cdn.index_url())
        return self._cdn_index

    def matrix_index(self) -> dict:
        if self._matrix_index is not None:
            return self._matrix_index

        env = UnityPy.load(self.get_blob("index"))

        if "assets/temp/index.bytes" not in env.container:
            raise SourceIndexError("Failed to find index in patch index bundle")

        index = loads_index(read_textasset_bytes(env, "assets/temp/index.bytes"))[0]
        self._matrix_index = index
        return index

    def has_blob(self, blob: str) -> bool:
        return blob in self.resources()

    def get_blob(self, blob: str) -> bytes:
        url = self.resources()[blob]
        self._logger.debug(f"Downloading blob {blob} ({url})")
        resp = get_session().get(url)
        if resp.status_code != 200:
            raise BlobDownloadError(
                f"Failed to download blob {blob} - {resp.status_code}"
            )
        return resp.content

    def version(self) -> Union[Tuple[int, ...], None]:
        return parse_version(self.cdn_index()[self._section]["version"])

    def base_path(self):
        url = self.cdn_index()[self._section]["resourcesBasePath"]
        if url[-1] != "/":
            url += "/"
        return url

    def blob_cdn_url(self):
        url = self.cdn_index()["default"]["cdnList"][0]["url"]
        if url[-1] != "/":
            url += "/"
        return url

    def bundle_to_blob(self, bundle: str) -> Union[str, None]:
        try:
            return self.matrix_index()[bundle][0]
        except KeyError:
            return None

    def bundle_sha1(self, bundle: str) -> Union[str, None]:
        try:
            return self.matrix_index()[bundle][1]
        except KeyError:
            return None

    def resources(self):
        if self._resources is not None:
            return self._resources

        blob_base = self.blob_cdn_url()

        resource_index = self._get_json(
            blob_base + self.cdn_index()[self._section]["resources"]
        )
        resources = {}
        for resource in resource_index["resource"]:
            dest = resource["dest"]
            # remove prefix slash if set
            if dest[0] == "/":
                dest = dest[1:]
            blob = dest.split("/")[-1]
            resources[blob] = blob_base + self.base_path() + dest
        self._resources = resources
        return resources

    def bundle_names(self):
        return self.matrix_index().keys()

    @staticmethod
    def _get_json(url: str) -> dict:
        resp = get_session().get(url)
        if resp.status_code != 200:
            raise BlobDownloadError(
                f"Failed to download json {url} - {resp.status_code}"
            )
        return resp.json()

    def __str__(self):
        return f"PcStarterSource({self._cdn_name})"
