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


class ContentCheckTests(unittest.TestCase):
    """The other four briefs, each with the answer worked out by hand."""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)

        self.folder = Path(self._temp.name)
        (self.folder / "output").mkdir()

    def docx(self, name: str, lines: list[str]) -> None:
        from docx import Document

        document = Document()

        for line in lines:
            document.add_paragraph(line)

        document.save(self.folder / "output" / name)

    def text(self, name: str, content: str) -> None:
        (self.folder / "output" / name).write_text(content, encoding="utf-8")

    def workbook(self, rows: list[tuple]) -> None:
        book = Workbook()
        page = book.active

        for row in rows:
            page.append(list(row))

        book.save(self.folder / "output" / "table.xlsx")

    def test_the_filtered_products_pass(self):
        self.docx("products.docx", ["Kettle 140", "Lamp 210", "Mug 320"])

        ok, note = bundled_eval.check_products(self.folder)

        self.assertTrue(ok, note)

    def test_an_unfiltered_list_is_caught(self):
        self.docx(
            "products.docx",
            ["Kettle 140", "Toaster 80", "Lamp 210", "Chair 35", "Mug 320"],
        )

        ok, note = bundled_eval.check_products(self.folder)

        self.assertFalse(ok)
        self.assertIn("Toaster", note)

    def test_a_good_workbook_beside_a_bad_document_still_passes(self):
        self.workbook(
            [("Product", "Units"), ("Kettle", 140), ("Lamp", 210), ("Mug", 320)]
        )
        self.docx("all.docx", ["Kettle", "Toaster", "Lamp", "Chair", "Mug"])

        ok, note = bundled_eval.check_products(self.folder)

        self.assertTrue(ok, note)
        self.assertIn("table.xlsx", note)

    def test_the_reorder_note_needs_items_and_quantities(self):
        self.text("note.md", "| Item | OnHand |\n| Widget | 12 |\n| Nut | 8 |\n")

        ok, note = bundled_eval.check_stock(self.folder)

        self.assertTrue(ok, note)

    def test_a_reorder_note_without_the_numbers_is_caught(self):
        self.text("note.md", "Please reorder Widget and Nut.")

        ok, note = bundled_eval.check_stock(self.folder)

        self.assertFalse(ok)
        self.assertIn("quantities", note)

    def test_the_cleaned_contacts_pass(self):
        self.text(
            "contacts.csv",
            "Name,Email\nAna Silva,ana@acme.example\nCara Diaz,cara@blueridge.example\n",
        )

        ok, note = bundled_eval.check_contacts(self.folder)

        self.assertTrue(ok, note)

    def test_an_untouched_contact_list_is_caught(self):
        self.text(
            "contacts.csv",
            "Name,Email\nAna Silva,ana@acme.example\nBen Okafor,\n"
            "Cara Diaz,cara@blueridge.example\nDan Wu,\n",
        )

        ok, note = bundled_eval.check_contacts(self.folder)

        self.assertFalse(ok)
        self.assertIn("Ben Okafor", note)

    def test_the_regional_totals_pass(self):
        self.workbook(
            [
                ("Region", "Revenue"),
                ("LatAm", 3530),
                ("Europe", 2740),
                ("Asia", 2240),
                ("Africa", 930),
            ]
        )

        ok, note = bundled_eval.check_sales(self.folder)

        self.assertTrue(ok, note)

    def test_a_total_that_ignores_the_threshold_is_caught(self):
        self.workbook(
            [
                ("Region", "Revenue"),
                ("LatAm", 4070),
                ("Europe", 3100),
                ("Asia", 1310),
                ("Africa", 1670),
            ]
        )

        ok, note = bundled_eval.check_sales(self.folder)

        self.assertFalse(ok)
        self.assertIn("regional totals", note)
