import hashlib
import logging
import os
import random
import string
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum
from typing import Union, Dict, Tuple, Iterable, Optional
from urllib.parse import urlparse

import UnityPy

from pgr_assets.versions import PATCH_KEY_SCHEME_MIN_VERSION, parse_version

from . import Source
from ._index import read_textasset_bytes, loads_index
from .exceptions import BlobDownloadError, SourceIndexError
from .session import get_session

SIGN_ALPHABET = string.ascii_letters + string.digits


@dataclass
class PatchCdnData:
    """
    Settings required to use a patch CDN for a server
    """

    cdn: str
    app_id: str
    platform: str
    key: Optional[str] = None
    sign: bool = False

    def config_url(self, version: str):
        path = [
            self.cdn,
            "client/config",
        ]

        if self.key and parse_version(version) >= PATCH_KEY_SCHEME_MIN_VERSION:
            path += [self.key]

        path += [
            self.app_id,
            version,
            self.platform,
            "config.tab",
        ]

        return "/".join(path)

    def base_url(self, application_version: str, document_version: str):
        path = [
            self.cdn,
            "client/patch",
        ]

        if (
            self.key
            and parse_version(application_version) >= PATCH_KEY_SCHEME_MIN_VERSION
        ):
            path += [self.key]

        path += [
            self.app_id,
            application_version,
            self.platform,
            document_version,
            "matrix/",
        ]

        return "/".join(path)


# CDN base url, app_id, platform From the config tab PrimaryCdn
# http://prod-encdn-akamai.kurogame.net/prod/client/config/com.kurogame.punishing.grayraven.en.pc/1.28.0/standalone/config.tab
class PatchCdn(Enum):
    EN = PatchCdnData(
        "http://prod-encdn-volcdn.kurogame.net/prod",
        "com.kurogame.punishing.grayraven.en",
        "android",
    )
    EN_PC = PatchCdnData(
        "http://prod-encdn-volcdn.kurogame.net/prod",
        "com.kurogame.punishing.grayraven.en",
        "standalone",
    )
    KR = PatchCdnData(
        "http://prod-krcdn-volcdn.kurogame.net/prod",
        "com.kurogame.punishing.grayraven.kr",
        "android",
    )
    KR_PC = PatchCdnData(
        "http://prod-krcdn-volcdn.kurogame.net/prod",
        "com.kurogame.punishing.grayraven.kr",
        "standalone",
    )

    JP = PatchCdnData(
        "http://prod-jpcdn-volcdn.kurogame.net/prod",
        "com.kurogame.punishing.grayraven.jp",
        "android",
    )
    JP_PC = PatchCdnData(
        "http://prod-jpcdn-volcdn.kurogame.net/prod",
        "com.kurogame.punishing.grayraven.jp",
        "standalone",
    )

    TW = PatchCdnData(
        "http://prod-twcdn-volcdn.kurogame.net/prod",
        "com.kurogame.punishing.grayraven.tw",
        "android",
    )
    TW_PC = PatchCdnData(
        "http://prod-twcdn-volcdn.kurogame.net/prod",
        "com.kurogame.punishing.grayraven.tw",
        "standalone",
    )

    # http://prod.zspnsalicdn.yingxiong.com/prod/client/config/com.kurogame.haru.kuro/2.9.0/standalone/config.tab
    CN = PatchCdnData(
        "http://prod-zspns-volccdn.kurogame.com/prod",
        "com.kurogame.haru.kuro",
        "android",
    )
    CN_PC = PatchCdnData(
        "http://prod-zspns-volccdn.kurogame.com/prod",
        "com.kurogame.haru.kuro",
        "standalone",
    )

    CN_BETA = PatchCdnData(
        "http://prod-zspns-volccdn.kurogame.com/prod",
        "com.kurogame.haru.kuro",
        "android",
        sign=True,
    )
    CN_PC_BETA = PatchCdnData(
        "http://prod-zspns-volccdn.kurogame.com/prod",
        "com.kurogame.haru.kuro",
        "standalone",
        sign=True,
    )


class PatchCdnSource(Source):
    _logger = logging.getLogger("PatchCdnSource")
    _cdn_name: str
    _cdn: PatchCdnData
    _index: Dict[str, Tuple[str, str, int]] | None = None
    _resources: Dict[str, str] | None = None
    _sign_key: str | None = None

    def __init__(self, cdn: PatchCdn, version: str, key: Optional[str] = None):
        self._cdn_name = cdn.name
        self._cdn = replace(cdn.value, key=key) if key else cdn.value

        if self._cdn.sign:
            self._sign_key = os.getenv("PATCH_SIGN_KEY")
            if not self._sign_key:
                self._logger.error("Beta selected but no PATCH_SIGN_KEY set")

        self._logger.debug("Getting config from patch cdn")
        config = self.get_tab(self._cdn.config_url(version))
        application_version = version
        document_version = config["DocumentVersion"]
        self._cdn_url = self._cdn.base_url(application_version, document_version)
        self._logger.debug(f"Using patch cdn {self._cdn_url}")
        self._version = application_version

    def has_blob(self, blob: str) -> bool:
        return blob in self.resources()

    def _request(self, url: str):
        if not self._cdn.sign:
            return get_session().get(url)

        # Do the new CN Beta signature
        expiration = int((datetime.now() + timedelta(minutes=30)).timestamp())
        random_str = "".join(random.choices(string.ascii_letters + string.digits, k=10))
        signature = f"{expiration}-{random_str}-0-"
        path = urlparse(url).path
        signature += hashlib.md5(
            f"{path}-{signature}{self._sign_key}".encode()
        ).hexdigest()
        return get_session().get(url + "?sign=" + signature)

    def get_blob(self, blob: str) -> bytes:
        url = self.resources()[blob]
        self._logger.debug(f"Downloading blob {blob} ({url})")
        resp = self._request(url)
        if resp.status_code != 200:
            raise BlobDownloadError(
                f"Failed to download blob {blob} - {resp.status_code}"
            )
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

    def resources(self) -> Dict[str, str]:
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
        bundle = self._request(f"{self._cdn_url}index")
        if bundle.status_code != 200:
            raise BlobDownloadError(
                f"Failed to download patch index - {bundle.status_code}"
            )
        env = UnityPy.load(bundle.content)

        if "assets/temp/index.bytes" in env.container:
            index = loads_index(read_textasset_bytes(env, "assets/temp/index.bytes"))[0]
        elif "assets/buildtemp/index.bytes" in env.container:
            partial_indices = loads_index(
                read_textasset_bytes(env, "assets/buildtemp/index.bytes")
            )
            index = partial_indices[0]
            for v in partial_indices[1].values():
                index.update(v)
        else:
            raise SourceIndexError("Failed to find index in patch index bundle")

        self._index = index
        return index

    def version(self) -> Union[Tuple[int, ...], None]:
        return parse_version(self._version)

    def bundle_names(self) -> Iterable[str]:
        return self.index().keys()

    @staticmethod
    def get_tab(url: str) -> Dict[str, str]:
        resp = get_session().get(url)
        if resp.status_code != 200:
            raise BlobDownloadError(
                f"Failed to download raw {url} - {resp.status_code}"
            )

        data = {}
        for line in resp.content.decode("utf-8").splitlines(False):
            if line.strip() == "":
                continue
            key, _, value = line.split("\t")
            data[key] = value

        return data

    def __str__(self):
        return f"PatchCdnSource({self._cdn_name})"
