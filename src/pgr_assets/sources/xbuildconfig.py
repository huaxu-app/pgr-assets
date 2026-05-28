import re
import struct
from dataclasses import dataclass
from io import BytesIO

import UnityPy

_KEY_RE = re.compile(r"^[A-Za-z0-9]{16}$")


class XBuildConfigError(Exception):
    pass


@dataclass
class XBuildConfig:
    bundle_id: str
    display_version: str
    internal_version: str
    build_number: str
    key: str


def _read_int(buf: BytesIO) -> int:
    data = buf.read(4)
    if len(data) != 4:
        raise XBuildConfigError("unexpected end of data reading int")
    return struct.unpack("<i", data)[0]


def _read_aligned_string(buf: BytesIO) -> str:
    raw_len = buf.read(4)
    if len(raw_len) != 4:
        raise XBuildConfigError("unexpected end of data reading string length")
    (length,) = struct.unpack("<i", raw_len)
    if length < 0 or length > 4096:
        raise XBuildConfigError(f"implausible string length {length}")
    data = buf.read(length)
    if len(data) != length:
        raise XBuildConfigError("unexpected end of data reading string body")
    buf.read((-length) & 3)  # 4-byte alignment padding
    return data.decode("utf-8")


def parse_xbuildconfig(raw: bytes) -> XBuildConfig:
    """Extract the per-build patch-CDN key from the XBuildConfig MonoBehaviour.

    XBuildConfig is a MonoBehaviour whose script isn't in the typetree, so UnityPy
    can't auto-deserialize it. The body is Unity's standard layout (MonoBehaviour
    header + length-prefixed, 4-aligned strings), which we walk by hand.
    """
    buf = BytesIO(raw)
    buf.read(12)  # m_GameObject
    buf.read(4)   # m_Enabled
    buf.read(12)  # m_Script

    m_name = _read_aligned_string(buf)
    if m_name != "XBuildConfig":
        raise XBuildConfigError(f"expected m_name 'XBuildConfig', got {m_name!r}")

    bundle_id = _read_aligned_string(buf)
    display_version = _read_aligned_string(buf)
    _read_int(buf)  # unknown int (0)
    internal_version = _read_aligned_string(buf)
    build_number = _read_aligned_string(buf)
    _read_int(buf)  # unknown int (4)
    key = _read_aligned_string(buf)

    if not _KEY_RE.match(key):
        raise XBuildConfigError(f"implausible patch key {key!r}")

    return XBuildConfig(
        bundle_id=bundle_id,
        display_version=display_version,
        internal_version=internal_version,
        build_number=build_number,
        key=key,
    )


def extract_build_key(resources_assets: bytes) -> str:
    """Load resources.assets, locate XBuildConfig, return its patch-CDN key."""
    env = UnityPy.load(resources_assets)
    try:
        obj = next(o for o in env.objects if o.peek_name() == "XBuildConfig")
    except StopIteration:
        raise XBuildConfigError("XBuildConfig object not found in resources.assets")
    return parse_xbuildconfig(obj.get_raw_data()).key
