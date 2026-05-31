import struct
import unittest
from pathlib import Path
from unittest import mock

from pgr_assets.extractors import bundle
from pgr_assets.extractors.helpers import (
    decrypt,
    is_utf8,
    rewrite_text_asset,
    try_convert_to_csv,
)

BINARYTABLE_FIXTURES = (
    Path(__file__).parent.parent / "converters" / "binarytable" / "fixtures"
)


def _nameless_table_bytes() -> bytes:
    """A binary table with one column whose name is empty and zero rows -- this is
    how binary blobs (navmesh, colliders, path areas) parse through the lenient
    parser. Layout is the pre-3.3 format used by the areastage fixture."""
    info = bytes(
        [
            0x01,  # column count = 1
            0x01,  # column 0 type = 1 (bool)
            0x00,  # column 0 name = "" (null terminator only)
            0x00,  # has_primary_key = 0
            0x00,  # row trunk length = 0
            0x00,  # row count = 0
            0x00,  # content trunk length = 0
        ]
    )
    return struct.pack("<i", len(info)) + info


class IsUtf8Test(unittest.TestCase):
    def test_valid_utf8(self):
        self.assertTrue(is_utf8("héllo".encode("utf-8")))

    def test_invalid_bytes(self):
        self.assertFalse(is_utf8(b"\xff\xfe\xff"))


class DecryptTest(unittest.TestCase):
    def test_rejects_offset_count_past_end(self):
        with self.assertRaises(ValueError):
            decrypt(b"\x00" * 4, offset=2, count=4)

    def test_returns_bytearray_of_equal_length(self):
        data = bytes(range(32))
        out = decrypt(data)
        self.assertIsInstance(out, bytearray)
        self.assertEqual(len(data), len(out))

    def test_is_deterministic(self):
        data = bytes(range(64))
        self.assertEqual(decrypt(data), decrypt(data))

    def test_does_not_mutate_input(self):
        original = bytearray(range(32))
        snapshot = bytes(original)
        decrypt(original)
        self.assertEqual(snapshot, bytes(original))

    def test_subrange_leaves_other_bytes_untouched(self):
        data = bytes(range(20))
        out = decrypt(data, offset=5, count=5)
        # Only [offset, offset+count) may change.
        self.assertEqual(data[:5], bytes(out[:5]))
        self.assertEqual(data[10:], bytes(out[10:]))


class TryConvertToCsvTest(unittest.TestCase):
    def test_valid_table_round_trips(self):
        raw = (BINARYTABLE_FIXTURES / "areastage.tab.bytes").read_bytes()
        csv = try_convert_to_csv(raw, (3, 0))
        assert csv is not None
        self.assertIn(b"Id", csv)

    def test_unparseable_returns_none(self):
        self.assertIsNone(try_convert_to_csv(b"not a valid binary table at all", (3, 0)))

    def test_nameless_blob_returns_none(self):
        # Parses, but columns are nameless -- a binary blob, not a real table.
        self.assertIsNone(try_convert_to_csv(_nameless_table_bytes(), (3, 0)))


class RewriteTextAssetTest(unittest.TestCase):
    def test_non_bytes_path_returned_unchanged(self):
        data = b"\x89PNG..."
        path, out = rewrite_text_asset("assets/foo.png", data, (3, 0))
        self.assertEqual("assets/foo.png", path)
        self.assertEqual(data, out)

    def test_drops_bytes_extension(self):
        path, out = rewrite_text_asset("assets/foo.json.bytes", b"{}", (3, 0))
        self.assertEqual("assets/foo.json", path)
        self.assertEqual(b"{}", out)

    def test_strips_rsa_signature_from_large_non_utf8(self):
        data = bytes(range(256))  # >128 bytes, not valid UTF-8
        path, out = rewrite_text_asset("assets/foo.bin.bytes", data, (3, 0))
        self.assertEqual("assets/foo.bin", path)
        self.assertEqual(data[128:], bytes(out))

    def test_keeps_large_utf8_payload_intact(self):
        data = ("a" * 200).encode("utf-8")  # >128 bytes, valid UTF-8
        path, out = rewrite_text_asset("assets/foo.txt.bytes", data, (3, 0))
        self.assertEqual("assets/foo.txt", path)
        self.assertEqual(data, out)

    def test_decrypts_non_utf8_lua(self):
        data = bytes([0xFF, 0x00, 0x42, 0x13, 0x37, 0x80])  # <=128, not UTF-8
        path, out = rewrite_text_asset("assets/script.lua.bytes", data, (3, 0))
        self.assertEqual("assets/script.lua", path)
        self.assertEqual(decrypt(data), out)

    def test_does_not_decrypt_utf8_lua(self):
        data = b"print('hi')"
        path, out = rewrite_text_asset("assets/script.lua.bytes", data, (3, 0))
        self.assertEqual("assets/script.lua", path)
        self.assertEqual(data, out)

    def test_converts_binary_table_under_temp_marker(self):
        raw = (BINARYTABLE_FIXTURES / "areastage.tab.bytes").read_bytes()
        path, out = rewrite_text_asset(
            "assets/temp/bytes/share/areastage.tab.bytes",
            raw,
            (3, 0),
            allow_binary_table_convert=True,
        )
        self.assertEqual("assets/temp/bytes/share/areastage.csv", path)
        self.assertIn(b"Id", bytes(out))

    def test_converts_plain_bytes_table(self):
        raw = (BINARYTABLE_FIXTURES / "areastage.tab.bytes").read_bytes()
        path, out = rewrite_text_asset(
            "assets/temp/bytes/share/fight/npc/areastage.bytes",
            raw,
            (3, 0),
            allow_binary_table_convert=True,
        )
        self.assertEqual("assets/temp/bytes/share/fight/npc/areastage.csv", path)
        self.assertIn(b"Id", bytes(out))

    def test_skips_nameless_blob_under_temp_marker(self):
        blob = _nameless_table_bytes()
        path, out = rewrite_text_asset(
            "assets/temp/bytes/share/fight/map/info/scene/patharea.tab.bytes",
            blob,
            (3, 0),
            allow_binary_table_convert=True,
        )
        self.assertEqual(
            "assets/temp/bytes/share/fight/map/info/scene/patharea.tab", path
        )
        self.assertEqual(blob, bytes(out))

    def test_does_not_convert_when_flag_disabled(self):
        raw = (BINARYTABLE_FIXTURES / "areastage.tab.bytes").read_bytes()
        path, out = rewrite_text_asset(
            "assets/temp/bytes/share/areastage.tab.bytes",
            raw,
            (3, 0),
            allow_binary_table_convert=False,
        )
        self.assertEqual("assets/temp/bytes/share/areastage.tab", path)
        self.assertEqual(raw, bytes(out))

    def test_converts_table_with_windows_separators(self):
        # On Windows the dest path uses backslashes; the forward-slash temp marker
        # must still match so binary tables are converted there too.
        raw = (BINARYTABLE_FIXTURES / "areastage.tab.bytes").read_bytes()
        win_path = "out\\assets\\temp\\bytes\\share\\areastage.tab.bytes"
        with mock.patch("pgr_assets.extractors.helpers.os.sep", "\\"):
            path, out = rewrite_text_asset(
                win_path, raw, (3, 0), allow_binary_table_convert=True
            )
        self.assertTrue(path.endswith("areastage.csv"))
        self.assertIn(b"Id", bytes(out))


class SaveImageThumbnailTest(unittest.TestCase):
    def test_rolecharacter_thumbnail_with_windows_separators(self):
        from PIL import Image

        img = Image.new("RGB", (512, 512))
        win_dest = "out\\assets\\product\\texture\\image\\rolecharacter\\r2\\foo.png"
        saved = []
        with (
            mock.patch("pgr_assets.extractors.bundle.os.sep", "\\"),
            mock.patch.object(Image.Image, "save", lambda self, p, **kw: saved.append(p)),
            mock.patch.object(Image.Image, "copy", lambda self: self),
            mock.patch.object(Image.Image, "thumbnail", lambda self, size: None),
        ):
            bundle.save_image(img, win_dest)
        # The marker-gated 256px thumbnail must be written despite backslashes.
        self.assertTrue(any(p.endswith(".256.webp") for p in saved))


if __name__ == "__main__":
    unittest.main()
