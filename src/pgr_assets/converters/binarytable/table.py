import csv
from dataclasses import dataclass
from typing import BinaryIO, List, IO, Dict

from .reader import Reader

@dataclass
class Column:
    name: str
    type: int
    list_length: int = 0
    dict_keys: list = None
    dict_key_presence: set = None

    def is_dict_type(self):
        return 9 <= self.type <= 13

    def is_int_keyed_dict(self):
        return self.type == 10 or self.type == 11 or self.type == 13

    def add_dict_key(self, key):
        if self.dict_keys is None:
            self.dict_keys = list()
            self.dict_key_presence = set()

        if key not in self.dict_key_presence:
            self.dict_key_presence.add(key)
            self.dict_keys.append(key)

class BinaryTable:
    reader: Reader

    info_length: int
    columns: List[Column]

    has_primary_key: bool
    primary_key: str|None
    primary_key_length: int

    row_trunk_length: int
    row_count: int
    content_trunk_length: int

    pool_column_size: int
    column_map: Dict[int, bool]
    pool_offset_info_array: List[int]
    pool_content_start_pos: int

    rows: List

    def __init__(self, data: BinaryIO, new_fixnum = False):
        self.reader = Reader(data, new_fixnum=new_fixnum)
        self.pool_column_size = -1
        self.column_map = {}
        self.pool_offset_info_array = []
        self.pool_content_start_pos = 0
        self.reader.set_string_pool_callback(self.read_pool_string_by_index)

        self._read_header()
        self._read_string_pool_info()
        self._read_content()

    def _read_header(self):
        self.info_length = self.reader.read_i32()
        self.columns = []

        for _ in range(self.reader.read_int()):
            column_type = self.reader.read_int()
            column_name = self.reader.read_string()
            self.columns.append(Column(column_name, column_type))

        self.has_primary_key = self.reader.read_bool()
        self.primary_key = ''
        self.primary_key_length = 0
        if self.has_primary_key:
            primary_key_index = self.reader.read_int() or 0
            self.primary_key = self.columns[primary_key_index].name
            self.primary_key_length = self.reader.read_int()

        self.row_trunk_length = self.reader.read_int()
        self.row_count = self.reader.read_int()
        self.content_trunk_length = self.reader.read_int()

        if self.content_trunk_length is None:
            self.content_trunk_length = 0
            self.row_count = 0

    def _get_pool_offset_trunk_start_position(self):
        return 4 + self.info_length + self.primary_key_length + self.row_trunk_length + self.content_trunk_length

    def _get_pool_content_trunk_start_position(self):
        return self._get_pool_offset_trunk_start_position() + self.pool_content_start_pos

    def _read_string_pool_info(self):
        if self.content_trunk_length == 0:
            self.pool_column_size = 0
            return

        position = self._get_pool_offset_trunk_start_position()
        if position <= 0:
            self.pool_column_size = 0
            return

        self.reader.seek(position)

        try:
            pool_head_length = self.reader.read_i32()
            if pool_head_length <= 0:
                self.pool_column_size = 0
                return
        except:
            self.pool_column_size = 0
            return

        self.pool_column_size = self.reader.read_int() or 0
        if self.pool_column_size <= 0:
            return

        string_pool_size = self.reader.read_int() or 0
        pool_column_len = self.reader.read_int() or 0
        pool_offset_trunk_len = self.reader.read_int() or 0
        pool_info_offset_len = pool_head_length + 4
        self.pool_content_start_pos = pool_info_offset_len + pool_column_len + pool_offset_trunk_len

        if pool_column_len <= 0:
            return

        self.column_map = {}
        for _ in range(self.pool_column_size):
            column_index = self.reader.read_int() or 0
            self.column_map[column_index + 1] = True

        if pool_offset_trunk_len <= 0:
            return

        self.pool_offset_info_array = []
        for _ in range(string_pool_size):
            self.pool_offset_info_array.append(self.reader.read_int() or 0)

    def _is_string_pool_column(self, column_index):
        if column_index < 0:
            return False
        if self.pool_column_size == -1:
            return False
        if self.pool_column_size <= 0:
            return False
        return self.column_map.get(column_index, False)

    def read_pool_string_by_index(self, index):
        if not self.pool_offset_info_array or len(self.pool_offset_info_array) <= 0:
            return ""

        if index + 1 > len(self.pool_offset_info_array):
            return ""

        pool_content_start_pos = self._get_pool_content_trunk_start_position()
        start_pos = 0 if index <= 0 else self.pool_offset_info_array[index - 1]
        end_pos = self.pool_offset_info_array[index]
        current_pos = self.reader.get_position()
        self.reader.seek(pool_content_start_pos + start_pos)
        old_use_pool = self.reader.use_string_pool
        # disable usage of the pool to read the string, then set it to its old value
        self.reader.set_use_string_pool(False)
        string_value = self.reader.read_string()
        self.reader.set_use_string_pool(old_use_pool)
        self.reader.seek(current_pos)
        return string_value

    def _read_content(self):
        if self.content_trunk_length == 0 or self.row_count == 0:
            self.rows = []
            return

        self.reader.seek(4 + self.info_length + self.primary_key_length + self.row_trunk_length)
        self.rows = [self._row(i) for i in range(self.row_count)]

    def _row(self, row_index: int):
        row = []
        for j, column in enumerate(self.columns):
            self.reader.set_use_string_pool(self._is_string_pool_column(j + 1))
            try:
                value = self.reader.read_by_column_type(column.type)
            except Exception as e:
                raise Exception(f"Error reading column {column.name} at row {row_index}", e)

            row.append(value)

            if (type(value) is list or column.is_int_keyed_dict()) and len(value) > column.list_length:
                column.list_length = len(value)
            elif column.is_dict_type():
                for key in value.keys():
                    column.add_dict_key(key)

        return row

    def csv_headers(self):
        for column in self.columns:
            if column.list_length > 0:
                for i in range(column.list_length):
                    yield f"{column.name}[{i}]"
            elif column.is_dict_type():
                for key in column.dict_keys or []:
                    yield f"{column.name}[{key}]"
            else:
                yield column.name

    def csv_row(self, row: List):
        for key, column in enumerate(self.columns):
            value = row[key]
            # Int dicts are lists if we squint hard enough
            if column.is_int_keyed_dict():
                for i in range(column.list_length):
                    yield value.get(i + 1, '')
            elif column.list_length > 0:
                for i in range(column.list_length):
                    yield value[i] if i < len(value) else ''
            # Stringy dicts have their own global key list
            elif column.is_dict_type():
                for k in column.dict_keys or []:
                    yield value.get(k, '')
            else:
                yield value

    def to_csv(self, file: IO):
        writer = csv.writer(file)
        writer.writerow(self.csv_headers())
        for row in self.rows:
            writer.writerow(self.csv_row(row))



