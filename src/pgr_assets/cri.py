"""
Single gateway to PyCriCodecsEx. Import CRI symbols from here, not directly,
so the GBK @UTF fallback installed below always applies.

Stock PyCriCodecsEx decodes @UTF strings as utf-8, shift-jis, then utf-16 and
raises otherwise. PGR's older USM movies have GBK-encoded CRID filenames that
fail all three. GBK is added as a last resort, so currently-decodable files keep
their existing result.
"""

import PyCriCodecsEx.utf as _utf
from PyCriCodecsEx.awb import AWB
from PyCriCodecsEx.chunk import UTFType, UTFTypeValues
from PyCriCodecsEx.hca import HCA
from PyCriCodecsEx.usm import USM
from PyCriCodecsEx.utf import UTF

__all__ = ["UTF", "USM", "AWB", "HCA", "UTFType", "UTFTypeValues"]

_ORIGINAL_FALLBACK = ("shift-jis", "utf-16")
_PATCHED_FALLBACK = ("shift-jis", "utf-16", "gbk")


def _install_gbk_fallback() -> None:
    code = _utf.UTF._read_rows_and_columns.__code__
    if _PATCHED_FALLBACK in code.co_consts:
        return
    if _ORIGINAL_FALLBACK not in code.co_consts:
        return
    new_consts = tuple(
        _PATCHED_FALLBACK if c == _ORIGINAL_FALLBACK else c for c in code.co_consts
    )
    _utf.UTF._read_rows_and_columns.__code__ = code.replace(co_consts=new_consts)


_install_gbk_fallback()
