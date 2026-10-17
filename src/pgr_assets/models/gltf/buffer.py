"""
Binary buffer views and accessors for a GLB document.
"""

import numpy as np
import pygltflib as gl


class Blob:
    """
    The GLB binary chunk, plus the views and accessors that index into it.
    """

    def __init__(self) -> None:
        self.data = bytearray()
        self.views: list[gl.BufferView] = []
        self.accessors: list[gl.Accessor] = []

    def _add_view(self, payload: bytes | memoryview, target: int | None) -> int:
        while len(self.data) % 4:
            self.data.append(0)
        offset = len(self.data)
        self.data += payload
        self.views.append(
            gl.BufferView(
                buffer=0, byteOffset=offset, byteLength=len(payload), target=target
            )
        )
        return len(self.views) - 1

    def _add(
        self,
        payload: np.ndarray,
        component: int,
        kind: str,
        target: int | None,
        bounds: bool = False,
    ) -> int:
        view = self._add_view(_view_bytes(payload), target)
        accessor = gl.Accessor(
            bufferView=view, componentType=component, count=len(payload), type=kind
        )
        if bounds:
            flat = payload.reshape(len(payload), -1)
            accessor.min = flat.min(axis=0).tolist()
            accessor.max = flat.max(axis=0).tolist()
        self.accessors.append(accessor)
        return len(self.accessors) - 1

    def add_vec2(self, values: np.ndarray) -> int:
        payload = np.ascontiguousarray(values, np.float32)
        return self._add(payload, gl.FLOAT, "VEC2", gl.ARRAY_BUFFER)

    def add_vec3(self, values: np.ndarray) -> int:
        payload = np.ascontiguousarray(values, np.float32)
        return self._add(payload, gl.FLOAT, "VEC3", gl.ARRAY_BUFFER, bounds=True)

    def add_vec4(self, values: np.ndarray) -> int:
        payload = np.ascontiguousarray(values, np.float32)
        return self._add(payload, gl.FLOAT, "VEC4", gl.ARRAY_BUFFER)

    def add_vec4_ushort(self, values: np.ndarray) -> int:
        payload = np.ascontiguousarray(values, np.uint16)
        return self._add(payload, gl.UNSIGNED_SHORT, "VEC4", gl.ARRAY_BUFFER)

    def add_mat4(self, values: np.ndarray) -> int:
        # glTF accessors are column major, Unity hands us row major.
        payload = np.ascontiguousarray(
            np.asarray(values, np.float32).transpose(0, 2, 1)
        )
        return self._add(payload, gl.FLOAT, "MAT4", None)

    def add_scalar(self, values: np.ndarray) -> int:
        payload = np.ascontiguousarray(values, np.uint32)
        return self._add(
            payload, gl.UNSIGNED_INT, "SCALAR", gl.ELEMENT_ARRAY_BUFFER, bounds=True
        )

    def add_image(self, payload: bytes) -> int:
        return self._add_view(payload, None)

    def add_index_view(self, indices: np.ndarray) -> int | None:
        if not len(indices):
            return None
        return self._add_view(_view_bytes(np.asarray(indices, np.uint32)), None)

    def add_sparse_vec3(
        self, index_view: int | None, values: np.ndarray, count: int
    ) -> int:
        # No bufferView on the base accessor, and glTF forbids byteOffset
        # without one too. pygltflib defaults byteOffset to 0, so it must be
        # cleared explicitly or the field serializes anyway.
        accessor = gl.Accessor(
            componentType=gl.FLOAT, count=count, type="VEC3", byteOffset=None
        )
        if not len(values):
            accessor.min = accessor.max = [0.0, 0.0, 0.0]
            self.accessors.append(accessor)
            return len(self.accessors) - 1

        assert index_view is not None
        payload = np.ascontiguousarray(values, np.float32)
        accessor.sparse = gl.Sparse(
            count=len(payload),
            indices=gl.AccessorSparseIndices(
                bufferView=index_view, byteOffset=0, componentType=gl.UNSIGNED_INT
            ),
            values=gl.AccessorSparseValues(
                bufferView=self._add_view(_view_bytes(payload), None), byteOffset=0
            ),
        )
        low, high = payload.min(axis=0), payload.max(axis=0)
        if len(payload) < count:
            # Every vertex the sparse block does not name yields zero, so the
            # bounds have to admit it. When it names all of them, they must not.
            low, high = np.minimum(low, 0.0), np.maximum(high, 0.0)
        accessor.min, accessor.max = low.tolist(), high.tolist()
        self.accessors.append(accessor)
        return len(self.accessors) - 1


def _view_bytes(array: np.ndarray) -> memoryview:
    """
    The array's bytes without a copy, so the blob takes one instead of two.
    """
    return memoryview(np.ascontiguousarray(array).reshape(-1).view(np.uint8))
