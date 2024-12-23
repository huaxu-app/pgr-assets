import csv
from dataclasses import dataclass
from typing import BinaryIO, List, IO

from .reader import Reader

@dataclass
class Column:
    name: str
    type: int
    list_length: int = 0

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

    def __init__(self, data: BinaryIO):
        self.reader = Reader(data)
        self.info_length = self.reader.read_i32()
        self.columns = []

        for _ in range(self.reader.read_int()):
            column_type = self.reader.read_int()
            column_name = self.reader.read_string()
            self.columns.append(Column(column_name, column_type))

        self.has_primary_key = self.reader.read_bool()
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

            if type(value) is list and len(value) > column.list_length:
                column.list_length = len(value)

        return row

    def csv_headers(self):
        for column in self.columns:
            if column.list_length > 0:
                for i in range(column.list_length):
                    yield f"{column.name}[{i}]"
            else:
                yield column.name

    @staticmethod
    def csv_row(row: List):
        for value in row:
            if type(value) is list:
                yield from value
            elif type(value) is dict:
                raise Exception("Cannot convert dict to CSV")
            else:
                yield value

    def to_csv(self, file: IO):
        writer = csv.writer(file)
        writer.writerow(self.csv_headers())
        for row in self.rows:
            writer.writerow(self.csv_row(row))



