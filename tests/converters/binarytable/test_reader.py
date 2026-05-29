import io
import unittest
from decimal import Decimal
from pgr_assets.converters.binarytable.reader import Reader


class ReaderTest(unittest.TestCase):
    def test_read_leb128(self):
        self.assertEqual(Reader(io.BytesIO(b"\x00")).read_leb128(), 0)
        self.assertEqual(Reader(io.BytesIO(b"\x01")).read_leb128(), 1)
        self.assertEqual(Reader(io.BytesIO(b"\x7f")).read_leb128(), 127)
        self.assertEqual(Reader(io.BytesIO(b"\x80\x01")).read_leb128(), 128)
        self.assertEqual(Reader(io.BytesIO(b"\xac\x02")).read_leb128(), 300)
        self.assertEqual(Reader(io.BytesIO(b"\xe5\xd8\x24")).read_leb128(), 601189)
        self.assertEqual(
            Reader(io.BytesIO(b"\xa2\xcc\xe8\x71")).read_leb128(), 238691874
        )

    def test_read_string(self):
        self.assertEqual(Reader(io.BytesIO(b"\x00")).read_string(), "")
        self.assertEqual(
            Reader(
                io.BytesIO(b"\x48\x65\x6c\x6c\x6f\x2c\x20\x57\x6f\x72\x6c\x64\x21\x00")
            ).read_string(),
            "Hello, World!",
        )

    def test_read_u8(self):
        self.assertEqual(Reader(io.BytesIO(b"\x01")).read_u8(), 1)
        self.assertEqual(Reader(io.BytesIO(b"\xff")).read_u8(), 255)

    def test_read_i32(self):
        self.assertEqual(Reader(io.BytesIO(b"\x01\x00\x00\x00")).read_i32(), 1)
        self.assertEqual(Reader(io.BytesIO(b"\xff\xff\xff\xff")).read_i32(), -1)

    def test_read_bool(self):
        self.assertTrue(Reader(io.BytesIO(b"\x01")).read_bool())
        self.assertFalse(Reader(io.BytesIO(b"\x00")).read_bool())

    def test_read_int(self):
        self.assertEqual(Reader(io.BytesIO(b"\x00")).read_int(), 0)
        self.assertEqual(Reader(io.BytesIO(b"\x80\x01")).read_int(), 128)
        self.assertEqual(Reader(io.BytesIO(b"\xff\xff\xff\xff\x0f")).read_int(), -1)

    def test_read_float(self):
        self.assertEqual(Reader(io.BytesIO(b"\x00")).read_float(), 0.0)
        self.assertEqual(Reader(io.BytesIO(b"\x80\x01")).read_float(), 0.0128)
        self.assertEqual(Reader(io.BytesIO(b"\xc0\x9a\x0c")).read_float(), 20)
        self.assertEqual(Reader(io.BytesIO(b"\xe5\xd8\x24")).read_float(), 60.1189)

    def test_read_list_string(self):
        self.assertEqual(
            Reader(io.BytesIO(b"\x02foo\x00bar\x00")).read_list_string(), ["foo", "bar"]
        )

    def test_read_list_bool(self):
        self.assertEqual(
            Reader(io.BytesIO(b"\x02\x01\x00")).read_list_bool(), [True, False]
        )

    def test_read_list_int(self):
        self.assertEqual(
            Reader(io.BytesIO(b"\x02\x80\x01\xff\xff\xff\xff\x0f")).read_list_int(),
            [128, -1],
        )

    def test_read_list_float(self):
        self.assertEqual(
            Reader(io.BytesIO(b"\x02\xe5\xd8\x24\x00")).read_list_float(),
            [60.1189, 0.0],
        )

    def test_read_dict_string_string(self):
        self.assertEqual(
            Reader(
                io.BytesIO(b"\x02key\x00value\x00a\x00b\x00")
            ).read_dict_string_string(),
            {"key": "value", "a": "b"},
        )

    def test_read_dict_int_int(self):
        self.assertEqual(
            Reader(io.BytesIO(b"\x01\x80\x01\xff\xff\xff\xff\x0f")).read_dict_int_int(),
            {128: -1},
        )

    def test_read_dict_int_string(self):
        self.assertEqual(
            Reader(io.BytesIO(b"\x01\x80\x01val\x00")).read_dict_int_string(),
            {128: "val"},
        )

    def test_read_dict_string_int(self):
        self.assertEqual(
            Reader(io.BytesIO(b"\x01key\x00\x80\x01")).read_dict_string_int(),
            {"key": 128},
        )

    def test_read_dict_int_float(self):
        self.assertEqual(
            Reader(io.BytesIO(b"\x01\x80\x01\xe5\xd8\x24")).read_dict_int_float(),
            {128: 60.1189},
        )

    # New-style fix encoding: leb128 magnitude, then a sign/shift byte
    # (bit 7 = negative, bits 0-6 = decimal shift). A zero fix is a lone 0x00.
    def test_read_fix2(self):
        self.assertEqual(
            Reader(io.BytesIO(b"\x0f\x01\x02\x80"), new_fixnum=True).read_fix2(),
            [Decimal("1.5"), Decimal("-2")],
        )

    def test_read_fix3(self):
        self.assertEqual(
            Reader(io.BytesIO(b"\x0f\x01\x02\x80\x00"), new_fixnum=True).read_fix3(),
            [Decimal("1.5"), Decimal("-2"), 0],
        )

    def test_read_fix_quaternion(self):
        self.assertEqual(
            Reader(
                io.BytesIO(b"\x00\x0f\x01\x00\x02\x80"), new_fixnum=True
            ).read_fix_quaternion(),
            [0, Decimal("1.5"), 0, Decimal("-2")],
        )

    def test_read_list_fix2(self):
        self.assertEqual(
            Reader(
                io.BytesIO(b"\x02\x0f\x01\x02\x80\x00\x00"), new_fixnum=True
            ).read_list_fix2(),
            [[Decimal("1.5"), Decimal("-2")], [0, 0]],
        )

    def test_read_list_fix3(self):
        self.assertEqual(
            Reader(io.BytesIO(b"\x01\x00\x00\x00"), new_fixnum=True).read_list_fix3(),
            [[0, 0, 0]],
        )

    def test_read_list_fix_quaternion(self):
        self.assertEqual(
            Reader(
                io.BytesIO(b"\x01\x00\x00\x00\x00"), new_fixnum=True
            ).read_list_fix_quaternion(),
            [[0, 0, 0, 0]],
        )
