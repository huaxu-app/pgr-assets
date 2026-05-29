"""Exception hierarchy for the sources layer.

Callers can catch :class:`SourceError` to handle any source failure, or a
specific subclass to distinguish "this bundle/blob doesn't exist" from "it
exists but couldn't be fetched/parsed".
"""


class SourceError(Exception):
    """Base class for all errors raised by the sources layer."""


class BlobNotFoundException(SourceError):
    """A bundle or blob could not be resolved in any configured source."""


class BlobDownloadError(SourceError):
    """A blob was located but could not be downloaded (e.g. non-200 response)."""


class SourceIndexError(SourceError):
    """A source's index/config bundle was missing or could not be parsed."""


class UnknownSourceError(SourceError):
    """An unknown primary/patch source type was requested."""
