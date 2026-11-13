from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from docx import Document

from tools.word import WordTool


class WordReadTableTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()

        self.path = Path(self._temp.name) / "source.docx"

        document = Document()
        document.add_paragraph("Quarterly notes")

        first = self._add_table(
            document,
            [
                ["Region", "Units"],
                ["North", "10"],
                ["South", "20"],
            ],
        )
        first.style = "Table Grid"

        second = self._add_table(
            document,
            [
                ["Quarter", "Owner", "Closed"],
                ["Q1", "Ana", "4"],
                ["Q2", "Bo", "6"],
            ],
        )

        titled = self._add_table(
            document,
            [
                ["Annual summary", ""],
                ["Product", "Total"],
                ["Widget", "12"],
            ],
        )

        document.save(self.path)

        self.tool = WordTool()

    def tearDown(self):
        self._temp.cleanup()

    @staticmethod
    def _add_table(document, values):
        table = document.add_table(
            rows=len(values),
            cols=len(values[0]),
        )

        for row_index, row in enumerate(values):
            for column_index, value in enumerate(row):
                table.cell(row_index, column_index).text = value

        return table

    def test_reads_first_table_headers_and_rows(self):
        result = self.tool.run(
            "read_table",
            {"path": str(self.path)},
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.data["headers"], ["Region", "Units"])
        self.assertEqual(
            result.data["rows"],
            [["North", "10"], ["South", "20"]],
        )
        self.assertEqual(result.data["row_count"], 2)
        self.assertEqual(result.data["column_count"], 2)
        self.assertEqual(result.data["table_count"], 3)

    def test_reads_table_by_index(self):
        result = self.tool.run(
            "read_table",
            {"path": str(self.path), "table": 1},
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            result.data["headers"],
            ["Quarter", "Owner", "Closed"],
        )
        self.assertEqual(
            result.data["rows"][1],
            ["Q2", "Bo", "6"],
        )

    def test_header_row_option(self):
        result = self.tool.run(
            "read_table",
            {
                "path": str(self.path),
                "table": 2,
                "header_row": 2,
            },
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            result.data["headers"],
            ["Product", "Total"],
        )
        self.assertEqual(result.data["rows"], [["Widget", "12"]])

    def test_max_rows_option(self):
        result = self.tool.run(
            "read_table",
            {"path": str(self.path), "max_rows": 1},
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.data["row_count"], 1)

    def test_table_index_out_of_range(self):
        result = self.tool.run(
            "read_table",
            {"path": str(self.path), "table": 9},
        )

        self.assertFalse(result.success)
        self.assertIn("out of range", result.error or "")

    def test_missing_path_argument(self):
        result = self.tool.run("read_table", {})

        self.assertFalse(result.success)
        self.assertIn("requires 'path'", result.error or "")
