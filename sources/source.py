from typing import Union, Dict, List


class Source(object):
    def has_blob(self, path: str) -> bool:
        """Returns true if the source has the blob at the given path"""
        raise NotImplementedError()

    def get_blob(self, path: str) -> bytes:
        """Returns the blob at the given path as binary data"""
        raise NotImplementedError()

    def bundle_sha1(self, path: str) -> Union[str, None]:
        """Returns the sha1 of the given blob"""
        raise NotImplementedError()

    def bundle_to_blob(self, bundle: str) -> Union[str, None]:
        """Returns the blob that contains the bundle, or None if unknown"""
        raise NotImplementedError()

    def version(self) -> Union[str, None]:
        """Returns the version of the source, or None if unknown"""
        raise NotImplementedError()

    def resources(self) -> Dict[str, str]:
        """Returns a dict of blob -> path"""
        raise NotImplementedError()

    def bundle_names(self) -> List[str]:
        """Returns a list of all bundle names"""
        raise NotImplementedError()
