"""Reading a delimited file as a table.

The prompt tells the planner that .csv and .tsv belong to the text tool, so
that tool has to be able to read one into headers and rows; otherwise the
advice sends it somewhere that cannot do the job.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.table import TableTool
from tools.text import TextTool


class TextReadTableTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)

        self.folder = Path(self._temp.name)
        self.tool = TextTool()

    def write(self, name: str, content: str) -> Path:
        path = self.folder / name
        path.write_text(content, encoding="utf-8")

        return path

    def test_a_csv_becomes_headers_and_rows(self):
        path = self.write(
            "contacts.csv",
            "Name,Email\nAna Silva,ana@acme.example\nBen Okafor,\n",
        )

        result = self.tool.run("read_table", {"path": str(path)})

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.data["headers"], ["Name", "Email"])
        self.assertEqual(len(result.data["rows"]), 2)
        self.assertEqual(result.data["row_count"], 2)

    def test_a_tsv_uses_tabs_by_default(self):
        path = self.write("stock.tsv", "Item\tUnits\nBolt\t400\n")

        result = self.tool.run("read_table", {"path": str(path)})

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.data["headers"], ["Item", "Units"])
        self.assertEqual(result.data["rows"], [["Bolt", "400"]])

    def test_a_semicolon_file_can_say_so(self):
        path = self.write("euro.csv", "Client;Total\nAcme;1200\n")

        result = self.tool.run(
            "read_table", {"path": str(path), "delimiter": ";"}
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.data["headers"], ["Client", "Total"])

    def test_blank_lines_are_ignored(self):
        path = self.write("a.csv", "Name,Email\n\nAna,ana@acme.example\n\n")

        result = self.tool.run("read_table", {"path": str(path)})

        self.assertEqual(result.data["row_count"], 1)

    def test_the_result_feeds_a_table_step(self):
        path = self.write(
            "products.csv",
            "Product,Units\nKettle,140\nToaster,80\nMug,320\n",
        )

        read = self.tool.run("read_table", {"path": str(path)})
        filtered = TableTool().run(
            "filter",
            {
                "headers": read.data["headers"],
                "rows": read.data["rows"],
                "column": "Units",
                "op": ">=",
                "value": 100,
            },
        )

        self.assertTrue(filtered.success, filtered.error)
        self.assertEqual(
            [row[0] for row in filtered.data["rows"]],
            ["Kettle", "Mug"],
        )

    def test_a_missing_file_is_explained(self):
        result = self.tool.run(
            "read_table", {"path": str(self.folder / "nope.csv")}
        )

        self.assertFalse(result.success)
        self.assertIn("not found", result.error)

    def test_a_header_row_past_the_end_is_explained(self):
        path = self.write("short.csv", "Name\n")

        result = self.tool.run(
            "read_table", {"path": str(path), "header_row": 5}
        )

        self.assertFalse(result.success)
        self.assertIn("no header row 5", result.error)
