import io
import unittest
from .reader import Reader


class ReaderTest(unittest.TestCase):
    def test_read_leb128(self):
        self.assertEqual(Reader(io.BytesIO(b'\x00')).read_leb128(), 0)
        self.assertEqual(Reader(io.BytesIO(b'\x01')).read_leb128(), 1)
        self.assertEqual(Reader(io.BytesIO(b'\x7F')).read_leb128(), 127)
        self.assertEqual(Reader(io.BytesIO(b'\x80\x01')).read_leb128(), 128)
        self.assertEqual(Reader(io.BytesIO(b'\xAC\x02')).read_leb128(), 300)
        self.assertEqual(Reader(io.BytesIO(b'\xE5\xD8\x24')).read_leb128(), 601189)
        self.assertEqual(Reader(io.BytesIO(b'\xa2\xcc\xe8\x71')).read_leb128(), 238691874)

    def test_read_string(self):
        self.assertEqual(Reader(io.BytesIO(b'\x00')).read_string(), '')
        self.assertEqual(Reader(io.BytesIO(b'\x48\x65\x6C\x6C\x6F\x2C\x20\x57\x6F\x72\x6C\x64\x21\x00')).read_string(), 'Hello, World!')

    def test_read_u8(self):
        self.assertEqual(Reader(io.BytesIO(b'\x01')).read_u8(), 1)
        self.assertEqual(Reader(io.BytesIO(b'\xFF')).read_u8(), 255)

    def test_read_i32(self):
        self.assertEqual(Reader(io.BytesIO(b'\x01\x00\x00\x00')).read_i32(), 1)
        self.assertEqual(Reader(io.BytesIO(b'\xFF\xFF\xFF\xFF')).read_i32(), -1)

    def test_read_bool(self):
        self.assertTrue(Reader(io.BytesIO(b'\x01')).read_bool())
        self.assertFalse(Reader(io.BytesIO(b'\x00')).read_bool())

    def test_read_int(self):
        self.assertEqual(Reader(io.BytesIO(b'\x00')).read_int(), 0)
        self.assertEqual(Reader(io.BytesIO(b'\x80\x01')).read_int(), 128)
        self.assertEqual(Reader(io.BytesIO(b'\xFF\xFF\xFF\xFF\x0F')).read_int(), -1)

    def test_read_float(self):
        self.assertEqual(Reader(io.BytesIO(b'\x00')).read_float(), 0.0)
        self.assertEqual(Reader(io.BytesIO(b'\x80\x01')).read_float(), 0.0128)
        self.assertEqual(Reader(io.BytesIO(b'\xc0\x9a\x0c')).read_float(), 20)
        self.assertEqual(Reader(io.BytesIO(b'\xE5\xD8\x24')).read_float(), 60.1189)

    def test_read_list_string(self):
        self.assertEqual(Reader(io.BytesIO(b'\x02foo\x00bar\x00')).read_list_string(), ['foo', 'bar'])

    def test_read_list_bool(self):
        self.assertEqual(Reader(io.BytesIO(b'\x02\x01\x00')).read_list_bool(), [True, False])

    def test_read_list_int(self):
        self.assertEqual(Reader(io.BytesIO(b'\x02\x80\x01\xFF\xFF\xFF\xFF\x0F')).read_list_int(), [128, -1])

    def test_read_list_float(self):
        self.assertEqual(Reader(io.BytesIO(b'\x02\xE5\xD8\x24\x00')).read_list_float(), [60.1189, 0.0])

    def test_read_dict_string_string(self):
        self.assertEqual(Reader(io.BytesIO(b'\x02key\x00value\x00a\x00b\x00')).read_dict_string_string(), {'key': 'value', 'a': 'b'})

    def test_read_dict_int_int(self):
        self.assertEqual(Reader(io.BytesIO(b'\x01\x80\x01\xFF\xFF\xFF\xFF\x0F')).read_dict_int_int(), {128: -1})

    def test_read_dict_int_string(self):
        self.assertEqual(Reader(io.BytesIO(b'\x01\x80\x01val\x00')).read_dict_int_string(), {128: 'val'})

    def test_read_dict_string_int(self):
        self.assertEqual(Reader(io.BytesIO(b'\x01key\x00\x80\x01')).read_dict_string_int(), {'key': 128})

    def test_read_dict_int_float(self):
        self.assertEqual(Reader(io.BytesIO(b'\x01\x80\x01\xE5\xD8\x24')).read_dict_int_float(), {128: 60.1189})
