import os
import struct
from typing import BinaryIO

MAX_I32 = 2_147_483_647
FLOAT_TO_INT = 10_000


class Reader:
    file: BinaryIO

    def __init__(self, file: BinaryIO):
        self.file = file

    def read_bytes(self, size):
        return self.file.read(size)

    def read_by_column_type(self, type: int):
        match type:
            case 1: return self.read_bool()
            case 2: return self.read_string()
            case 3: return self.read_fix()
            case 4: return self.read_list_string()
            case 5: return self.read_list_bool()
            case 6: return self.read_list_int()
            case 7: return self.read_list_float()
            case 8: return self.read_list_fix()
            case 9: return self.read_dict_string_string()
            case 10: return self.read_dict_int_int()
            case 11: return self.read_dict_int_string()
            case 12: return self.read_dict_string_int()
            case 13: return self.read_dict_int_float()
            case 14: return self.read_int()
            case 15: return self.read_float()
            case _: raise Exception(f"Unknown column type: {type}")


    def read_u8(self):
        return struct.unpack('<B', self.read_bytes(1))[0]

    def read_i32(self):
        return struct.unpack('<i', self.read_bytes(4))[0]

    def read_leb128(self):
        result = 0
        shift = 0
        while True:
            byte = self.read_u8()
            result |= (byte & 0x7F) << shift
            if byte & 0x80 == 0:
                break
            shift += 7
        return result

    def read_bool(self):
        return self.read_u8() == 1

    def read_string(self):
        chars = bytearray([])
        while True:
            byte = self.read_u8()
            if byte == 0:  # Null byte indicates the end of the string
                break
            chars.append(byte)
        return chars.decode('utf-8')

    def read_int(self):
        x = self.read_leb128()
        # Bounds to signed i32 range
        return x if x <= MAX_I32 else -(((~x) & MAX_I32) + 1)

    def read_float(self):
        x = self.read_int()
        if x == 0:
            return 0.0

        return x / FLOAT_TO_INT

    def read_list_string(self):
        count = self.read_int()
        return [self.read_string() for _ in range(count)]

    def read_list_bool(self):
        count = self.read_int()
        return [self.read_bool() for _ in range(count)]

    def read_list_int(self):
        count = self.read_int()
        return [self.read_int() for _ in range(count)]

    def read_list_float(self):
        count = self.read_int()
        return [self.read_float() for _ in range(count)]

    def _read_dict(self, key_fn, value_fn):
        count = self.read_int()
        d = {}
        for _ in range(count):
            key = key_fn()
            value = value_fn()
            d[key] = value
        return d

    def read_dict_string_string(self):
        return self._read_dict(self.read_string, self.read_string)

    def read_dict_int_int(self):
        return self._read_dict(self.read_int, self.read_int)

    def read_dict_int_string(self):
        return self._read_dict(self.read_int, self.read_string)

    def read_dict_string_int(self):
        return self._read_dict(self.read_string, self.read_int)

    def read_dict_int_float(self):
        return self._read_dict(self.read_int, self.read_float)

    def read_fix(self):
        n = self.read_string()
        if n == '':
            return 0
        raise Exception(f"Unimplemented fix-conversion: {n}")

    def read_list_fix(self):
        count = self.read_int()
        return [self.read_fix() for _ in range(count)]

    def seek(self, position, from_where=os.SEEK_SET):
        self.file.seek(position, from_where)





