import os
import struct
from decimal import Decimal
from typing import BinaryIO, Callable, Optional

from .exceptions import BinaryTableError

MAX_I32 = 2_147_483_647
FLOAT_TO_INT = 10_000


class Reader:
    buffer: bytes
    pos: int
    new_fixnum: bool
    use_string_pool: bool
    string_pool_callback: Optional[Callable[[int], str]]

    # New style fixnum is from 3.3.0 (Jetavie) onwards
    def __init__(self, file: BinaryIO, new_fixnum=False):
        # The whole stream is slurped once so the hot read paths work against an
        # in-memory bytes buffer with an integer cursor, instead of issuing a
        # per-byte file.read()/struct.unpack for every value.
        self.buffer = file.read()
        self.pos = 0
        self.new_fixnum = new_fixnum
        self.use_string_pool = False
        self.string_pool_callback = None

    def set_string_pool_callback(self, callback: Callable[[int], str]):
        self.string_pool_callback = callback

    def read_bytes(self, size):
        start = self.pos
        self.pos = end = start + size
        return self.buffer[start:end]

    def read_by_column_type(self, type: int):
        match type:
            case 1:
                return self.read_bool()
            case 2:
                return self.read_string()
            case 3:
                return self.read_fix()
            case 4:
                return self.read_list_string()
            case 5:
                return self.read_list_bool()
            case 6:
                return self.read_list_int()
            case 7:
                return self.read_list_float()
            case 8:
                return self.read_list_fix()
            case 9:
                return self.read_dict_string_string()
            case 10:
                return self.read_dict_int_int()
            case 11:
                return self.read_dict_int_string()
            case 12:
                return self.read_dict_string_int()
            case 13:
                return self.read_dict_int_float()
            case 14:
                return self.read_int()
            case 15:
                return self.read_float()
            case 16:
                return self.read_fix2()
            case 17:
                return self.read_fix3()
            case 18:
                return self.read_fix_quaternion()
            case 19:
                return self.read_list_fix2()
            case 20:
                return self.read_list_fix3()
            case 21:
                return self.read_list_fix_quaternion()
            case _:
                raise BinaryTableError(f"Unknown column type: {type}")

    def read_u8(self):
        pos = self.pos
        self.pos = pos + 1
        return self.buffer[pos]

    def read_i32(self):
        # struct.unpack still raises struct.error on a short read at EOF, which
        # _read_string_pool_info relies on to detect a missing pool trailer.
        return struct.unpack("<i", self.read_bytes(4))[0]

    def read_leb128(self):
        buffer = self.buffer
        pos = self.pos
        result = 0
        shift = 0
        while True:
            byte = buffer[pos]
            pos += 1
            result |= (byte & 0x7F) << shift
            if byte & 0x80 == 0:
                break
            shift += 7
        self.pos = pos
        return result

    def read_bool(self):
        return self.read_u8() == 1

    def read_string(self, force_use_pool=None):
        # If using string pool, get string from the pool
        if force_use_pool is True or (force_use_pool is None and self.use_string_pool):
            index = self.read_int() or 0
            if self.string_pool_callback:
                return self.string_pool_callback(index)
            return ""

        buffer = self.buffer
        start = self.pos
        end = buffer.index(0, start)  # Null byte indicates the end of the string
        self.pos = end + 1
        return buffer[start:end].decode("utf-8")

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
        # Option 1: old style:
        # Either empty (0x00) or string (with 0x00 terminator)
        # behavior maps either way, assume that if first byte is actually NUL we don't have to do anything
        if not self.new_fixnum:
            n = self.read_string()
            if n == "":
                return 0
            return Decimal(n)

        # Option 2: new style
        # uLEB128 encoded number followed by an u8
        # the u8 indicates sign
        num = Decimal(self.read_leb128())
        if num == 0:
            return 0

        shift = self.read_bytes(1)[0]
        flip_sign = bool(shift & 0x80)
        shift = shift & (0x80 - 1)

        num = num.scaleb(-1 * shift)
        if flip_sign:
            return -num
        return num

    def read_list_fix(self):
        count = self.read_int()
        return [self.read_fix() for _ in range(count)]

    def read_fix2(self):
        return [self.read_fix(), self.read_fix()]

    def read_fix3(self):
        return [self.read_fix(), self.read_fix(), self.read_fix()]

    def read_fix_quaternion(self):
        return [self.read_fix(), self.read_fix(), self.read_fix(), self.read_fix()]

    def read_list_fix2(self):
        count = self.read_int()
        return [self.read_fix2() for _ in range(count)]

    def read_list_fix3(self):
        count = self.read_int()
        return [self.read_fix3() for _ in range(count)]

    def read_list_fix_quaternion(self):
        count = self.read_int()
        return [self.read_fix_quaternion() for _ in range(count)]

    def peek_byte(self):
        return self.buffer[self.pos]

    def seek(self, position, from_where=os.SEEK_SET):
        if from_where == os.SEEK_SET:
            self.pos = position
        elif from_where == os.SEEK_CUR:
            self.pos += position
        elif from_where == os.SEEK_END:
            self.pos = len(self.buffer) + position
        else:
            raise ValueError(f"Invalid seek origin: {from_where}")

    def move(self, offset):
        self.pos += offset

    def get_position(self):
        return self.pos
