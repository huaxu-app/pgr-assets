from typing import Union, Dict, Iterable, Tuple


class Source(object):
    def has_blob(self, blob: str) -> bool:
        """Returns true if the source has the blob at the given path"""
        raise NotImplementedError()

    def get_blob(self, blob: str) -> bytes:
        """Returns the blob at the given path as binary data"""
        raise NotImplementedError()

    def bundle_sha1(self, bundle: str) -> Union[str, None]:
        """Returns the sha1 of the given blob"""
        raise NotImplementedError()

    def bundle_to_blob(self, bundle: str) -> Union[str, None]:
        """Returns the blob that contains the bundle, or None if unknown"""
        raise NotImplementedError()

    def version(self) -> Union[Tuple[int, ...], None]:
        """Returns the version of the source, or None if unknown"""
        raise NotImplementedError()

    def resources(self) -> Dict[str, str]:
        """Returns a dict of blob -> path"""
        raise NotImplementedError()

    def bundle_names(self) -> Iterable[str]:
        """Returns all bundle names"""
        raise NotImplementedError()
