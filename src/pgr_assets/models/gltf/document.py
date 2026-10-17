import json

import pygltflib as gl


class Document(gl.GLTF2):
    """
    A glTF document that keeps empty containers inside `extras`.
    """

    def gltf_to_json(self, separators=None, indent="  ") -> str:
        return json.dumps(
            self._prune(gl.gltf_asdict(self)),
            cls=gl.JsonEncoder,
            default=gl.json_serial,
            indent=indent,
            separators=separators,
            allow_nan=False,
            skipkeys=True,
        )

    @classmethod
    def _prune(cls, value: object) -> object:
        if isinstance(value, list):
            return [cls._prune(item) for item in value]
        if not isinstance(value, dict):
            return value

        kept = {}
        for key, item in value.items():
            if item is None or (
                not isinstance(item, str)
                and hasattr(item, "__iter__")
                and not len(item)  # type: ignore[arg-type]
            ):
                continue
            kept[key] = item if key in ("extras", "extensions") else cls._prune(item)
        return kept
