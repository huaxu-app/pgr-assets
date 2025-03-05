import io
import os
from typing import Tuple

from pgr_assets.converters.binarytable.table import BinaryTable


def decrypt(content, offset=None, count=None):
    x_crypto_key = bytearray(
        [103, 40, 227, 236, 173, 175, 148, 243, 66, 252, 58, 22, 68, 192, 159, 15, 187, 15, 15, 29, 209, 209, 212, 66,
         104, 16, 252, 194, 227, 14, 116, 112, 196, 221, 5, 1, 4, 173, 165, 69, 45, 193, 95, 10, 67, 38, 167, 239, 96,
         184, 133, 75, 152, 196, 36, 121, 251, 7, 73, 82, 219, 25, 118, 70, 153, 232, 120, 120, 147, 10, 88, 106, 214,
         187, 216, 49, 224, 57, 1, 233, 110, 40, 65, 85, 246, 197, 4, 20, 56, 74, 245, 41, 63, 169, 188, 104, 89, 49,
         115, 254, 100, 77, 79, 11, 148, 242, 95, 88, 241, 111, 48, 130, 169, 200, 224, 135, 121, 161, 72, 84, 5, 100,
         135, 70, 141, 94, 244, 114, 58, 28, 87, 181, 205, 221, 154, 184, 197, 98, 210, 202, 252, 124, 144, 9, 112, 163,
         24, 254, 119, 188, 5, 230, 40, 79, 171, 17, 156, 212, 134, 41, 79, 134, 26, 251, 123, 219, 191, 136, 21, 84,
         192, 91, 24, 33, 68, 101, 85, 61, 186, 215, 191, 37, 45, 51, 117, 227, 14, 145, 56, 43, 32, 67, 48, 98, 192,
         41, 136, 223, 50, 163, 97, 251, 174, 59, 59, 147, 237, 177, 31, 159, 52, 243, 245, 247, 148, 139, 21, 92, 139,
         80, 47, 4, 105, 59, 227, 220, 180, 231, 176, 187, 205, 203, 148, 121, 98, 90, 87, 131, 245, 3, 63, 239, 57,
         117, 102, 134, 40, 172, 60, 128, 108, 102, 216, 247, 133, 102])
    content = content.copy()
    if offset is None:
        offset = 0
    if count is None:
        count = len(content)
    if len(content) < offset + count:
        raise Exception("Invalid offset+count")

    # One specific byte from the key is chosen to xor with everything? Why?
    num = count % len(x_crypto_key)
    for i in reversed(range(count)):
        # i loops backwards, calculate actual index based on offset param
        num2 = i + offset
        # num3 is actual byte
        num3 = content[num2]
        # Ok... (next byte or 0 if out of bounds) + number of bytes % 8, why?
        num4 = ((content[num2 + 1] if i + 1 < count else 0) + count) % 8
        num3 = num3 >> 8 - num4 | num3 << num4
        num3 ^= x_crypto_key[i % len(x_crypto_key)]

        if num2 > offset:
            num3 ^= content[num2 - 1]

        num3 ^= x_crypto_key[num]
        content[num2] = num3 & 0xFF

    return content


def is_utf8(data: bytes) -> bool:
    try:
        data.decode('utf-8')
        return True
    except UnicodeDecodeError:
        return False

def convert_to_csv(data: memoryview, new_fixnum=False) -> bytearray:
    try:
        output = io.StringIO(newline='')
        table = BinaryTable(io.BytesIO(data), new_fixnum=new_fixnum)
        table.to_csv(output)
        return bytearray(output.getvalue().encode())
    except Exception as e:
        raise e

def rewrite_text_asset(path: str, data: memoryview, allow_binary_table_convert=False, new_fixnum=False) -> Tuple[str, bytearray]:
    if '/temp/bytes/' in path:
        if allow_binary_table_convert:
            data = convert_to_csv(data, new_fixnum=new_fixnum)
            path = path.replace('.tab.bytes', '.csv')
            if path.endswith('.bytes'):
                # Extremely weird case where its usually a directory
                path_without_bytes, _ = os.path.splitext(path)
                path = os.path.join(path_without_bytes, os.path.basename(path_without_bytes) + '.csv')
    elif len(data) > 128 and not is_utf8(data):
        # RSA signature can fuck itself
        data = bytearray(data[128:])

    # Almost all files end with .bytes
    # If it doesn't, we'll keep it as it is,
    # otherwise we drop the '.bytes' extension
    path_without_bytes, ext = os.path.splitext(path)
    if ext != ".bytes":
        return path, data

    path = path_without_bytes
    ext = os.path.splitext(path)[1]

    if ext == ".lua":
        return path, decrypt(data)

    return path, data
