import unittest
from pathlib import Path

from pgr_assets.converters.binarytable.exceptions import BinaryTableError
from pgr_assets.extractors.helpers import (
    convert_to_csv,
    decrypt,
    is_utf8,
    rewrite_text_asset,
)

BINARYTABLE_FIXTURES = (
    Path(__file__).parent.parent / "converters" / "binarytable" / "fixtures"
)


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


class ConvertToCsvTest(unittest.TestCase):
    def test_valid_table_round_trips(self):
        raw = (BINARYTABLE_FIXTURES / "areastage.tab.bytes").read_bytes()
        csv = convert_to_csv(raw, (3, 0))
        self.assertIn(b"Id", csv)

    def test_malformed_raises_binarytable_error(self):
        with self.assertRaises(BinaryTableError):
            convert_to_csv(b"not a valid binary table at all", (3, 0))


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


if __name__ == "__main__":
    unittest.main()
