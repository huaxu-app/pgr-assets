from typing import Union, Dict, Tuple
from zipfile import ZipFile

import UnityPy
import msgpack

from sources import Source


class ObbSource(Source):
    _resources = None
    _index = None

    def __init__(self, obb: str):
        self._obb = ZipFile(obb, 'r')

    def has_blob(self, blob: str) -> bool:
        return blob in self.resources()

    def get_blob(self, blob: str) -> bytes:
        return self._obb.read(self.resources()[blob])

    def bundle_to_blob(self, bundle: str) -> Union[str, None]:
        try:
            return self.index()[bundle][0]
        except KeyError:
            return None

    def version(self) -> Union[str, None]:
        return None

    def index(self) -> Dict[str, Tuple[str, int, int]]:
        if self._index is not None:
            return self._index

        # msgpack.loads(UnityPy.load(primary_source.get_blob('index')).container['assets/buildtemp/index.bytes'].read().script)[0]
        index_blob = self._obb.read('assets/resource/matrix/index')
        env = UnityPy.load(index_blob)

        if 'assets/buildtemp/index.bytes' not in env.container:
            raise Exception(f"Invalid OBB index bundle")

        self._index = msgpack.loads(env.container['assets/buildtemp/index.bytes'].read().script)[0]
        return self._index

    def resources(self) -> Dict[str, str]:
        if self._resources is not None:
            return self._resources

        self._resources = {f.filename.split('/')[-1]: f.filename for f in self._obb.filelist if 'matrix' in f.filename}
        return self._resources

    def bundle_names(self):
        return self.index().keys()

    def __str__(self):
        return f"ObbSource({self._obb.filename})"

