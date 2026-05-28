import unittest
from pathlib import Path

from pgr_assets.sources.xbuildconfig import (
    XBuildConfig,
    XBuildConfigError,
    parse_xbuildconfig,
)

FIXTURE = Path(__file__).parent / "fixtures" / "xbuildconfig_en_4.4.0.bin"


class ParseXBuildConfigTest(unittest.TestCase):
    def test_parses_known_fixture(self):
        config = parse_xbuildconfig(FIXTURE.read_bytes())
        self.assertIsInstance(config, XBuildConfig)
        self.assertEqual(config.key, "R0bYNv1p0RHLXEEe")
        self.assertEqual(config.bundle_id, "com.kurogame.punishing.grayraven.en")
        self.assertEqual(config.display_version, "4.4.0")
        self.assertEqual(config.internal_version, "4.4.0")
        self.assertEqual(config.build_number, "1774577433")

    def test_rejects_wrong_name(self):
        raw = bytearray(FIXTURE.read_bytes())
        raw[32:44] = b"YBuildConfig"  # corrupt m_name (12-byte string at offset 32)
        with self.assertRaises(XBuildConfigError):
            parse_xbuildconfig(bytes(raw))

    def test_rejects_truncated(self):
        with self.assertRaises(XBuildConfigError):
            parse_xbuildconfig(b"\x00" * 8)


if __name__ == "__main__":
    unittest.main()
