from typing import Union, Dict, Tuple
from zipfile import ZipFile

import UnityPy
import msgpack

from . import Source


class ObbSource(Source):
    _resources = None
    _obb_path: str
    _filename: str
    _index = None

    def __init__(self, obb: str):
        self._obb_path = obb
        obb = ZipFile(obb, 'r')
        self.load_index(obb)
        self._resources = {f.filename.split('/')[-1]: f.filename for f in obb.filelist if 'matrix' in f.filename}
        self._filename = obb.filename

    def has_blob(self, blob: str) -> bool:
        return blob in self.resources()

    def get_blob(self, blob: str) -> bytes:
        return ZipFile(self._obb_path, 'r').read(self.resources()[blob])

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

    def index(self) -> Dict[str, Tuple[str, str, int]]:
        return self._index

    def load_index(self, obb):
        index_blob = obb.read('assets/resource/matrix/index')
        env = UnityPy.load(index_blob)

        if 'assets/buildtemp/index.bytes' not in env.container:
            raise Exception("Invalid OBB index bundle")

        self._index = msgpack.loads(env.container['assets/buildtemp/index.bytes'].read().m_Script.encode('utf-8', 'surrogateescape'))[0]

    def resources(self) -> Dict[str, str]:
        return self._resources

    def bundle_names(self):
        return self.index().keys()

    def __str__(self):
        return f"ObbSource({self._filename})"

