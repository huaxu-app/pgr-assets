import io
import os
import unittest

from converters.binarytable.table import BinaryTable

script_dir = os.path.dirname(__file__)


class TableTest(unittest.TestCase):
    def test_headers(self):
        with open(os.path.join(script_dir, 'assets/areastage.tab.bytes'), 'rb') as f:
            table = BinaryTable(f)
            self.assertEqual(105, table.info_length)
            self.assertEqual(10, len(table.columns))

            self.assertEqual('Id', table.columns[0].name)
            self.assertEqual(14, table.columns[0].type)

            self.assertEqual('StageId', table.columns[6].name)
            self.assertEqual(6, table.columns[6].type)

            self.assertEqual(True, table.has_primary_key)
            self.assertEqual('Id', table.primary_key)
            self.assertEqual(29, table.primary_key_length)

            self.assertEqual(115, table.row_trunk_length)
            self.assertEqual(29, table.row_count)
            self.assertEqual(7202, table.content_trunk_length)

    def test_rows(self):
        with open(os.path.join(script_dir, 'assets/areastage.tab.bytes'), 'rb') as f:
            table = BinaryTable(f)
            rows = table.rows

        self.assertEqual(29, len(rows))
        row = rows[0]
        self.assertEqual(1, row[0])
        self.assertEqual([1, 2, 3], row[7])

        # Check if properly propagated
        self.assertEqual(3, table.columns[8].list_length)

    def test_csv_headers(self):
        with open(os.path.join(script_dir, 'assets/areastage.tab.bytes'), 'rb') as f:
            table = BinaryTable(f)

        self.assertEqual(frozenset([
            'Id', 'Name', 'BuffId', 'BuffDesc', 'StageId[0]', 'StageId[1]', 'StageId[2]', 'ActiveAutoFightStageStr[0]',
            'ActiveAutoFightStageStr[1]', 'ActiveAutoFightStageStr[2]', 'MarkId[0]', 'MarkId[1]', 'MarkId[2]',
            'AutoFight[0]', 'AutoFight[1]', 'AutoFight[2]', 'Desc', 'Region'
        ]), frozenset(list(table.csv_headers())))

    def test_to_csv(self):
        out = io.StringIO(newline='')
        with open(os.path.join(script_dir, 'assets/areastage.tab.bytes'), 'rb') as f:
            BinaryTable(f).to_csv(out)

        out.seek(0)
        string = out.read().splitlines()

        with open(os.path.join(script_dir, 'assets/areastage.csv'), 'r') as f:
            expected = f.read().splitlines()
        self.assertEqual(expected, string)
