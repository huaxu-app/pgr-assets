import csv
from dataclasses import dataclass
from typing import BinaryIO, List, IO

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

    rows: List

    def __init__(self, data: BinaryIO, new_fixnum = False):
        self.reader = Reader(data, new_fixnum=new_fixnum)
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
            self.primary_key = self.reader.read_string()
            self.primary_key_length = self.reader.read_int()

        self.row_trunk_length = self.reader.read_int()
        self.row_count = self.reader.read_int()
        self.content_trunk_length = self.reader.read_int()

        self.reader.seek(4 + self.info_length + self.primary_key_length + self.row_trunk_length)
        self.rows = [self._row(i) for i in range(self.row_count)]

    def _row(self, row_index: int):
        row = []
        for column in self.columns:
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



