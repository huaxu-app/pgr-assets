"""Exceptions for the binary-table parser.

Callers can catch :class:`BinaryTableError` to distinguish a malformed or
unsupported ``.tab.bytes`` from a genuine programming error.
"""


class BinaryTableError(Exception):
    """A binary table could not be parsed (malformed, truncated, or unsupported)."""
