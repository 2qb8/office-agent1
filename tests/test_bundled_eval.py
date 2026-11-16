"""A file in output/ is not an answer.

The eval used to call a job correct when it left a non-empty workbook
behind. The invoice case did exactly that with one row per client and the
first amount instead of the sum, so the content check is the thing standing
between a real result and a flattering one.
"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook


SCRIPT = (
    Path(__file__).resolve().parent.parent / "scripts" / "bundled_eval.py"
)

spec = importlib.util.spec_from_file_location("bundled_eval", SCRIPT)
bundled_eval = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundled_eval)


class InvoiceCheckTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)

        self.folder = Path(self._temp.name)
        (self.folder / "output").mkdir()

    def write(self, rows: list[tuple]) -> None:
        book = Workbook()
        page = book.active
        page.title = "Summary"

        for row in rows:
            page.append(list(row))

        book.save(self.folder / "output" / "summary.xlsx")

    def test_the_right_totals_pass(self):
        self.write(
            [
                ("Client", "Total Amount"),
                ("Blue Ridge", 2250.75),
                ("Acme Ltd", 2000),
                ("Northwind", 430.5),
            ]
        )

        ok, note = bundled_eval.check_invoice(self.folder)

        self.assertTrue(ok, note)
        self.assertIn("sorted", note)

    def test_one_row_per_client_is_caught(self):
        # The shape a first-row-wins aggregate produces: non-empty, plausible,
        # and wrong.
        self.write(
            [
                ("Client", "Total Amount"),
                ("Acme Ltd", 1200),
                ("Northwind", 340.5),
                ("Blue Ridge", 2250.75),
            ]
        )

        ok, note = bundled_eval.check_invoice(self.folder)

        self.assertFalse(ok)
        self.assertIn("Acme Ltd 1200 instead of 2000", note)

    def test_the_wrong_order_is_caught(self):
        self.write(
            [
                ("Client", "Total Amount"),
                ("Acme Ltd", 2000),
                ("Blue Ridge", 2250.75),
                ("Northwind", 430.5),
            ]
        )

        ok, note = bundled_eval.check_invoice(self.folder)

        self.assertFalse(ok)
        self.assertIn("not sorted", note)

    def test_a_missing_client_is_caught(self):
        self.write(
            [
                ("Client", "Total Amount"),
                ("Acme Ltd", 2000),
                ("Northwind", 430.5),
            ]
        )

        ok, note = bundled_eval.check_invoice(self.folder)

        self.assertFalse(ok)
        self.assertIn("Blue Ridge", note)

    def test_no_workbook_is_not_a_pass(self):
        ok, note = bundled_eval.check_invoice(self.folder)

        self.assertFalse(ok)
        self.assertIn("no workbook", note)
