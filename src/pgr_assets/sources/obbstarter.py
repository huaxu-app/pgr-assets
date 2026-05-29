from typing import Union, Dict, Iterable, Tuple
from zipfile import ZipFile

import UnityPy

from . import Source
from ._index import read_textasset_bytes, loads_index
from .exceptions import SourceIndexError


def _obb_resource_map(filenames) -> Dict[str, str]:
    resources = {name.split("/")[-1]: name for name in filenames if "matrix" in name}
    for name in filenames:
        if name.split("/")[-1] == "resources.assets":
            resources["resources.assets"] = name
            break
    return resources


class ObbSource(Source):
    _obb_path: str
    _filename: str
    _index: dict
    _resources: Dict[str, str]

    def __init__(self, obb: str):
        self._obb_path = obb
        zf = ZipFile(obb, "r")
        self.load_index(zf)
        self._resources = _obb_resource_map([f.filename for f in zf.filelist])
        self._filename = zf.filename or obb

    def has_blob(self, blob: str) -> bool:
        return blob in self.resources()

    def get_blob(self, blob: str) -> bytes:
        return ZipFile(self._obb_path, "r").read(self.resources()[blob])

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

    def version(self) -> Union[Tuple[int, ...], None]:
        return None

    def index(self) -> dict:
        return self._index

    def load_index(self, obb: ZipFile):
        index_blob = obb.read("assets/resource/matrix/index")
        env = UnityPy.load(index_blob)

        if "assets/buildtemp/index.bytes" not in env.container:
            raise SourceIndexError("Invalid OBB index bundle")

        self._index = loads_index(
            read_textasset_bytes(env, "assets/buildtemp/index.bytes")
        )[0]

    def resources(self) -> Dict[str, str]:
        return self._resources

    def bundle_names(self) -> Iterable[str]:
        return self.index().keys()

    def __str__(self):
        return f"ObbSource({self._filename})"
