import io
import os
import unittest
from decimal import Decimal

from .table import BinaryTable

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



    def test_old_style_fixnum(self):
        with open(os.path.join(script_dir, 'assets/npcsettletime.old.tab.bytes'), 'rb') as f:
            table = BinaryTable(f)
            rows = table.rows

        self.assertEqual(81, len(rows))
        # First row had 0 as SettleTime
        row = rows[0]
        self.assertEqual(Decimal('0'), row[3])

        # Row 17 was the first with a non-zero
        row = rows[16]
        self.assertEqual(Decimal('5.5'), row[3])

        # Row 51 was with 2 decimals
        row = rows[50]
        self.assertEqual(Decimal('4.15'), row[3])


    def test_new_style_fixnum(self):
        with open(os.path.join(script_dir, 'assets/npcsettletime.tab.bytes'), 'rb') as f:
            table = BinaryTable(f, new_fixnum=True)
            rows = table.rows

        self.assertEqual(81, len(rows))
        # First row had 0 as SettleTime
        row = rows[0]
        self.assertEqual(Decimal('0'), row[3])

        # Row 17 was the first with a non-zero
        row = rows[16]
        self.assertEqual(Decimal('5.5'), row[3])

        # Row 51 was with 2 decimals
        row = rows[50]
        self.assertEqual(Decimal('4.15'), row[3])


    def test_old_style_fixnum_npcsearcher(self):
        with open(os.path.join(script_dir, 'assets/npcsearcher.old.bytes'), 'rb') as f:
            table = BinaryTable(f)
            rows = table.rows

        # has both a negative number and a small number
        row = rows[0]
        self.assertEqual(Decimal('-4'), row[4])
        self.assertEqual(Decimal('1'), row[5])

    def test_new_style_fixnum_npcsearcher(self):
        with open(os.path.join(script_dir, 'assets/npcsearcher.bytes'), 'rb') as f:
            table = BinaryTable(f, new_fixnum=True)
            rows = table.rows

        # has both a negative number and a small number
        row = rows[0]
        self.assertEqual(Decimal('-4'), row[4])
        self.assertEqual(Decimal('1'), row[5])
